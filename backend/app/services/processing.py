"""End-to-end processing pipeline, run via FastAPI BackgroundTasks.

No queue/worker system (per project constraints): the webhook handler schedules
``process_meeting`` as a background task and returns immediately. The pipeline
updates the meeting's ``status`` at each stage so the UI can poll progress.

Pipeline: Recording -> Transcript -> MOM

Stages:
  1. download recording from Recall.ai -> S3
  2. extract audio with ffmpeg -> S3
  3. transcribe with WhisperX
  4. diarize with pyannote
  5. merge transcript + speakers -> save + S3
  6. GPT-4o MOM (generated from the transcript only)
"""
from __future__ import annotations

import logging
import os
import traceback

import httpx

from app.config import settings
from app.models.enums import MeetingStatus
from app.repositories.meeting_repo import MeetingRepository
from app.services.audio_service import extract_audio
from app.services.diarization_service import get_diarization_service
from app.services.generation_service import GenerationService
from app.services.merge_service import merge_transcript_with_speakers
from app.services.recall_service import RecallService
from app.services.s3_service import S3Service
from app.services.transcription_service import get_transcription_service

logger = logging.getLogger(__name__)


def _work_paths(meeting_id: str) -> tuple[str, str, str]:
    base = os.path.join(settings.work_dir, meeting_id)
    os.makedirs(base, exist_ok=True)
    return (
        os.path.join(base, "recording.mp4"),
        os.path.join(base, "audio.wav"),
        base,
    )


async def _try_upload(
    s3: S3Service, local_path: str, key: str, content_type: str, meeting_id: str, repo, tag: str
) -> bool:
    """Best-effort S3 upload. Returns True on success, False on failure.

    Archival uploads (recording/audio) must never abort the pipeline, since the
    transcript + MOM are produced from the local files. A failure is logged and
    surfaced as a non-fatal ``storage_warning`` on the meeting.
    """
    try:
        await s3.upload_file(local_path, key, content_type=content_type)
        logger.info("%s S3 upload OK: %s", tag, key)
        return True
    except Exception as exc:  # noqa: BLE001 — archival is best-effort
        message = str(exc) or type(exc).__name__
        logger.exception("%s S3 upload FAILED (continuing): %s", tag, key)
        await repo.update(
            meeting_id, {"storage_warning": f"S3 upload of {key} failed: {message}"}
        )
        return False


async def _download(url: str, dest: str) -> None:
    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            with open(dest, "wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=1 << 20):
                    f.write(chunk)


async def process_meeting(meeting_id: str, db) -> None:
    """Run the full pipeline for one meeting. Safe to call as a BackgroundTask."""
    repo = MeetingRepository(db)
    s3 = S3Service()
    video_path, audio_path, _ = _work_paths(meeting_id)

    logger.info("=== Pipeline START for meeting %s ===", meeting_id)
    try:
        meeting = await repo.get(meeting_id)
        if not meeting:
            logger.error("Pipeline aborted: meeting %s not found.", meeting_id)
            return

        # Clear any stale warnings/errors from a previous run so a successful
        # re-run doesn't keep showing an old "diarization skipped" banner.
        await repo.update(
            meeting_id,
            {"diarization_error": None, "storage_warning": None, "error": None},
        )

        # --- 1. download recording from Recall ---
        await repo.set_status(meeting_id, MeetingStatus.DOWNLOADING)
        recall = RecallService()
        recording_url = await recall.get_recording_url(meeting["recall_bot_id"])
        if not recording_url:
            raise RuntimeError("Recall recording URL not available yet.")
        logger.info("[1/6] Downloading recording for meeting %s ...", meeting_id)
        await _download(recording_url, video_path)
        # S3 upload is archival only (used for in-app playback). It must NOT block
        # transcript/MOM — transcription runs off the local audio file. If the
        # upload fails (e.g. a flaky network dropping a large multipart upload),
        # log it, record a warning, and continue.
        rec_key = f"meetings/{meeting_id}/recording.mp4"
        if await _try_upload(s3, video_path, rec_key, "video/mp4", meeting_id, repo, "[1/6]"):
            await repo.update(meeting_id, {"recording_s3_key": rec_key})

        # --- 2. extract audio ---
        await repo.set_status(meeting_id, MeetingStatus.EXTRACTING_AUDIO)
        logger.info("[2/6] Extracting audio (ffmpeg) for meeting %s ...", meeting_id)
        await extract_audio(video_path, audio_path)
        audio_key = f"meetings/{meeting_id}/audio.wav"
        # Also archival/best-effort — transcription below uses ``audio_path``.
        if await _try_upload(s3, audio_path, audio_key, "audio/wav", meeting_id, repo, "[2/6]"):
            await repo.update(meeting_id, {"audio_s3_key": audio_key})

        # --- 3. transcribe ---
        await repo.set_status(meeting_id, MeetingStatus.TRANSCRIBING)
        logger.info("[3/6] Transcription STARTED (WhisperX) for meeting %s ...", meeting_id)
        try:
            transcript_raw = await get_transcription_service().transcribe(audio_path)
        except Exception:
            logger.exception("[3/6] Transcription FAILED for meeting %s.", meeting_id)
            raise
        logger.info(
            "[3/6] Transcription COMPLETED: %d segments (lang=%s).",
            len(transcript_raw.get("segments", [])),
            transcript_raw.get("language"),
        )

        # --- 4. speaker labels ---
        # Two sources, in order of preference:
        #   (a) Recall's speaker_timeline — REAL participant names (e.g.
        #       "Bhumika Girhare") from the meeting platform. Best quality.
        #   (b) pyannote diarization — voice-only "Speaker 1/2/3" fallback when
        #       Recall participant data isn't available.
        # Speaker labels are NOT required for transcript/MOM, so any failure here
        # is non-fatal: we log it and continue with whatever (or nothing) we got.
        await repo.set_status(meeting_id, MeetingStatus.DIARIZING)
        speaker_turns: list = []

        # (a) Try Recall real names first.
        try:
            speaker_turns = await recall.get_speaker_timeline(meeting["recall_bot_id"])
            if speaker_turns:
                logger.info(
                    "[4/6] Using Recall speaker names: %d turns, speakers=%s.",
                    len(speaker_turns),
                    sorted({t["speaker"] for t in speaker_turns}),
                )
        except Exception:  # noqa: BLE001 — fall back to pyannote
            logger.exception("[4/6] Recall speaker_timeline fetch failed; trying pyannote.")

        # (b) Fall back to pyannote diarization if Recall gave us nothing.
        if not speaker_turns:
            logger.info("[4/6] Diarization STARTED (pyannote) for meeting %s ...", meeting_id)
            try:
                # A user-provided speaker count constrains pyannote and prevents
                # over-segmenting one voice into several on short/noisy audio.
                num_speakers = meeting.get("num_speakers")
                speaker_turns = await get_diarization_service().diarize(
                    audio_path, num_speakers=num_speakers
                )
                logger.info(
                    "[4/6] Diarization COMPLETED: %d speaker turns (num_speakers=%s).",
                    len(speaker_turns),
                    num_speakers or "auto",
                )
            except Exception as exc:  # noqa: BLE001 — diarization is best-effort
                speaker_turns = []
                message = str(exc) or type(exc).__name__
                logger.exception(
                    "[4/6] Diarization FAILED for meeting %s (continuing without speaker "
                    "labels): %s",
                    meeting_id,
                    message,
                )
                await repo.update(
                    meeting_id,
                    {"diarization_error": f"Speaker diarization skipped: {message}"},
                )

        # --- 5. merge ---
        await repo.set_status(meeting_id, MeetingStatus.MERGING)
        merged = merge_transcript_with_speakers(transcript_raw, speaker_turns)
        await repo.save_transcript(meeting_id, merged)
        tr_key = f"meetings/{meeting_id}/transcript.txt"
        await s3.upload_bytes(merged["full_text"].encode("utf-8"), tr_key, "text/plain")
        await repo.update(meeting_id, {"transcript_s3_key": tr_key})
        logger.info("[5/6] Transcript merged & saved to MongoDB + S3 (%s).", tr_key)

        full_text = merged["full_text"]

        # Guard: never generate a summary from an empty transcript (no hallucinations).
        if not full_text.strip():
            logger.warning(
                "Transcript empty for meeting %s — skipping MOM/extraction.", meeting_id
            )
            await repo.set_status(meeting_id, MeetingStatus.COMPLETED)
            return

        # --- 6. MOM (generated only from the transcript) ---
        await repo.set_status(meeting_id, MeetingStatus.GENERATING_MOM)
        logger.info("[6/6] MOM generation STARTED (GPT-4o) for meeting %s ...", meeting_id)
        generator = GenerationService()
        try:
            mom = await generator.generate_mom(full_text)
        except Exception:
            logger.exception("[6/6] MOM generation FAILED for meeting %s.", meeting_id)
            raise
        await repo.save_mom(meeting_id, mom)
        logger.info("[6/6] MOM generation COMPLETED & saved to MongoDB.")

        await repo.set_status(meeting_id, MeetingStatus.COMPLETED)
        logger.info("=== Pipeline COMPLETED for meeting %s ===", meeting_id)
    except Exception as exc:  # noqa: BLE001 — record and surface any stage failure
        logger.exception("=== Pipeline FAILED for meeting %s: %s ===", meeting_id, exc)
        traceback.print_exc()
        # Some exceptions (e.g. NotImplementedError) stringify to "" — keep the type.
        message = str(exc) or f"{type(exc).__name__}"
        await repo.set_status(meeting_id, MeetingStatus.FAILED, error=message)
    finally:
        _cleanup(video_path, audio_path)


def _cleanup(*paths: str) -> None:
    for p in paths:
        try:
            if os.path.exists(p):
                os.remove(p)
        except OSError:
            pass
