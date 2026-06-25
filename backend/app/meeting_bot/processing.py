"""Orchestration for the meeting-bot flow.

Three groups of operations, all status-based and isolated so one failure never
breaks the others (per the business rules):

  * ``finalize_meeting`` — runs when the meeting ends: finalize live transcript,
    upload audio+video to S3, generate live MoM (from the live transcript only).
  * ``run_media_transcription`` — optional, user-triggered audio/video re-run.
  * ``run_source_mom`` — optional, user-triggered MoM from audio/video transcript.
"""
from __future__ import annotations

import logging
import os
import traceback

from app.meeting_bot import audio_service, models as M, video_service
from app.meeting_bot.embedding_service import embed_chunks
from app.meeting_bot.live_events import broker
from app.meeting_bot.mom_service import MomService
from app.meeting_bot.recall_service import MeetingBotRecall
from app.meeting_bot.repository import MeetingBotRepository
from app.meeting_bot.s3_service import MeetingBotS3
from app.meeting_bot.models import MomStatus, RecordingStatus, Source, TranscriptStatus
from app.meeting_bot.transcription_service import transcribe_to_chunks
from app.meeting_bot.utils import new_correlation_id, now, segments_to_text

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Post-meeting finalization (automatic)
# --------------------------------------------------------------------------- #
async def finalize_meeting(meeting_id: str, db) -> None:
    repo = MeetingBotRepository(db)
    s3 = MeetingBotS3()
    recall = MeetingBotRecall()
    cid = new_correlation_id()
    logger.info("[%s] FINALIZE meeting %s START", cid, meeting_id)

    meeting = await repo.get_meeting(meeting_id)
    if not meeting:
        logger.error("[%s] finalize aborted: meeting %s missing", cid, meeting_id)
        return
    bot_id = meeting.get("bot_id")

    # Immediately reflect "meeting ended — preparing" in the UI.
    await repo.update_meeting(meeting_id, {
        "status": M.MeetingStatus.PROCESSING.value,
        "bot_status": M.BotStatus.LEFT.value,
        "recording_status": RecordingStatus.UPLOADING.value,
    })
    await broker.publish(meeting_id, "status", {"status": M.MeetingStatus.PROCESSING.value})

    # --- 1. finalize live transcript from collected chunks (independent) ---
    try:
        chunks = await repo.get_chunks(meeting_id, Source.LIVE.value, limit=100000)
        live_text = "\n".join(
            f"[{_ts(c.get('start_time'))}] {c.get('speaker_name') or 'Unknown'}: {c['text']}"
            for c in chunks if c.get("text")
        )
        if live_text.strip():
            await s3.upload_bytes(live_text.encode(), "transcript_live", meeting_id, "text/plain")
            await repo.update_meeting(meeting_id, {
                "live_transcript_text": live_text,
                "live_transcript_status": TranscriptStatus.GENERATED.value,
            })
            logger.info("[%s] live transcript finalized (%d chunks)", cid, len(chunks))
        else:
            await repo.update_meeting(meeting_id, {
                "live_transcript_status": TranscriptStatus.NOT_STARTED.value,
            })
            logger.warning("[%s] no live transcript chunks (live captions not received)", cid)
    except Exception:
        logger.exception("[%s] live transcript finalize failed", cid)
        await repo.update_meeting(meeting_id, {"live_transcript_status": TranscriptStatus.FAILED.value})

    # --- 2. upload audio + video recordings to S3 (each independent) ---
    urls = {}
    try:
        urls = await recall.get_recording_urls(bot_id) if bot_id else {}
    except Exception:
        logger.exception("[%s] could not fetch recording URLs", cid)
    await _store_recording(repo, s3, meeting_id, "audio", urls.get("audio"), cid)
    await _store_recording(repo, s3, meeting_id, "video", urls.get("video"), cid)

    # --- 3. MoM from live transcript (if live captions were captured) ---
    fresh = await repo.get_meeting(meeting_id)
    live_text = (fresh or {}).get("live_transcript_text") or ""
    if live_text.strip():
        # Live captions were captured → MoM from the live transcript.
        await _generate_and_save_mom(repo, s3, meeting_id, Source.LIVE, live_text, cid)
    else:
        # No live captions (e.g. no public webhook URL configured).
        # Audio/video transcripts are only generated when the user explicitly
        # clicks the button — never auto-triggered here.
        logger.info(
            "[%s] no live transcript — audio/video transcripts available on demand via UI buttons",
            cid,
        )
        await repo.update_meeting(meeting_id, {"live_mom_status": MomStatus.NOT_STARTED.value})

    await repo.update_meeting(meeting_id, {
        "status": M.MeetingStatus.COMPLETED.value,
        "completed_at": now(),
    })
    await broker.publish(meeting_id, "meeting_completed", {"meeting_id": meeting_id})
    logger.info("[%s] FINALIZE meeting %s DONE", cid, meeting_id)


async def _store_recording(repo, s3, meeting_id, rec_type, source_url, cid) -> None:
    """Download a recording from Recall and upload it to S3 (best-effort)."""
    status_field = f"{rec_type}_recording_status"
    url_field = f"{rec_type}_recording_url"
    if not source_url:
        logger.warning("[%s] no %s recording URL available", cid, rec_type)
        await repo.update_meeting(meeting_id, {status_field: RecordingStatus.FAILED.value})
        return
    base = audio_service.work_dir(meeting_id)
    ext = "mp4" if rec_type == "video" else "mp3"
    local = os.path.join(base, f"recording.{ext}")
    kind = "video" if rec_type == "video" else "audio"
    ctype = "video/mp4" if rec_type == "video" else "audio/mpeg"
    try:
        await repo.update_meeting(meeting_id, {status_field: RecordingStatus.UPLOADING.value})
        await audio_service.download(source_url, local)
        await s3.upload_file(local, kind, meeting_id, ctype)
        presigned = await s3.presigned_url(kind, meeting_id, expires_in=7 * 24 * 3600)
        size = os.path.getsize(local) if os.path.exists(local) else None
        await repo.save_recording(meeting_id, rec_type, {
            "s3_key": M.s3_key(kind, meeting_id), "s3_url": presigned,
            "file_size": size, "format": ext, "status": "uploaded",
        })
        await repo.update_meeting(meeting_id, {
            status_field: RecordingStatus.UPLOADED.value, url_field: presigned,
        })
        logger.info("[%s] %s recording uploaded to S3", cid, rec_type)
    except Exception:
        logger.exception("[%s] %s recording upload failed (falling back to source URL)", cid, rec_type)
        # Fall back to the (time-limited) Recall URL so playback still works.
        await repo.update_meeting(meeting_id, {
            status_field: RecordingStatus.FAILED.value, url_field: source_url,
        })
    finally:
        _cleanup(local)


# --------------------------------------------------------------------------- #
# Optional user-triggered media transcription (audio or video)
# --------------------------------------------------------------------------- #
async def run_media_transcription(meeting_id: str, source: Source, db) -> None:
    assert source in (Source.AUDIO, Source.VIDEO)
    repo = MeetingBotRepository(db)
    s3 = MeetingBotS3()
    recall = MeetingBotRecall()
    cid = new_correlation_id()
    status_field = f"{source.value}_transcript_status"
    text_field = f"{source.value}_transcript_text"
    kind = source.value  # "audio" | "video"
    logger.info("[%s] %s transcription START for %s", cid, source.value, meeting_id)

    meeting = await repo.get_meeting(meeting_id)
    if not meeting:
        return
    await repo.update_meeting(meeting_id, {status_field: TranscriptStatus.GENERATING.value})
    await broker.publish(meeting_id, "status", {status_field: TranscriptStatus.GENERATING.value})

    from app.config import settings

    base = audio_service.work_dir(meeting_id)
    media_local = os.path.join(base, f"src.{ 'mp4' if source == Source.VIDEO else 'mp3'}")
    wav_local = os.path.join(base, f"{source.value}.wav")
    try:
        # 1. fetch media: prefer S3, fall back to a fresh Recall URL.
        await _fetch_media(repo, s3, recall, meeting, kind, media_local, cid)

        # 2. AssemblyAI works best on the original MP3/MP4 (full quality).
        #    Only convert to WAV when falling back to WhisperX (which requires it).
        use_assemblyai = bool(settings.assemblyai_api_key)
        if use_assemblyai:
            # Pass the original file directly — no quality loss from WAV conversion.
            audio_for_transcription = media_local
            logger.info("[%s] AssemblyAI path: using original %s (no WAV conversion)", cid, kind)
        elif source == Source.VIDEO:
            wav_local = await video_service.video_to_wav(media_local, meeting_id)
            audio_for_transcription = wav_local
        else:
            wav_local = await audio_service.ensure_wav(media_local, wav_local)
            audio_for_transcription = wav_local

        # 3. real speaker names (Recall timeline) if available, else pyannote.
        speaker_turns = None
        if not use_assemblyai:  # AssemblyAI does its own diarization
            try:
                if meeting.get("bot_id"):
                    turns = await recall.get_speaker_timeline(meeting["bot_id"])
                    speaker_turns = turns or None
            except Exception:
                logger.warning("[%s] speaker timeline unavailable; using pyannote", cid)

        # 4. transcribe -> chunks.
        chunks, full_text, detected_lang = await transcribe_to_chunks(
            audio_for_transcription, meeting_id, meeting.get("bot_id"), source,
            num_speakers=meeting.get("num_speakers"), speaker_turns=speaker_turns,
        )
        if detected_lang:
            logger.info("[%s] detected language: %s", cid, detected_lang)

        # 5. optional embeddings (best-effort).
        await embed_chunks(chunks)

        # 6. persist chunks + full text + S3.
        await repo.replace_chunks(meeting_id, source.value, chunks)
        await s3.upload_bytes(full_text.encode(), f"transcript_{kind}", meeting_id, "text/plain")
        lang_update = {f"{source.value}_transcript_language": detected_lang} if detected_lang else {}
        await repo.update_meeting(meeting_id, {
            text_field: full_text,
            status_field: TranscriptStatus.GENERATED.value,
            **lang_update,
        })
        await broker.publish(meeting_id, "status", {status_field: TranscriptStatus.GENERATED.value})
        logger.info("[%s] %s transcription DONE (%d chunks)", cid, source.value, len(chunks))
    except Exception as exc:  # noqa: BLE001 — isolated; never breaks other flows
        logger.exception("[%s] %s transcription FAILED", cid, source.value)
        traceback.print_exc()
        await repo.update_meeting(meeting_id, {
            status_field: TranscriptStatus.FAILED.value,
            f"{source.value}_transcript_error": str(exc) or type(exc).__name__,
        })
        await broker.publish(meeting_id, "status", {status_field: TranscriptStatus.FAILED.value})
    finally:
        # Always clean up the original media file.
        # Only clean up WAV if it was actually created (not needed for AssemblyAI path).
        _cleanup(media_local)
        if wav_local and os.path.exists(wav_local):
            _cleanup(wav_local)


async def _fetch_media(repo, s3, recall, meeting, kind, dest, cid) -> None:
    meeting_id = meeting["id"]
    # Try S3 first.
    try:
        await s3.download_to(kind, meeting_id, dest)
        if os.path.getsize(dest) > 0:
            logger.info("[%s] fetched %s from S3", cid, kind)
            return
    except Exception:
        logger.info("[%s] %s not in S3; trying Recall", cid, kind)
    # Fall back to Recall.
    bot_id = meeting.get("bot_id")
    if not bot_id:
        raise RuntimeError(f"{kind} media unavailable: no S3 file and no bot id")
    urls = await recall.get_recording_urls(bot_id)
    url = urls.get(kind)
    if not url:
        raise RuntimeError(f"{kind} media unavailable from Recall")
    await audio_service.download(url, dest)


# --------------------------------------------------------------------------- #
# Optional user-triggered MoM from a given source transcript
# --------------------------------------------------------------------------- #
async def run_source_mom(meeting_id: str, source: Source, db) -> None:
    repo = MeetingBotRepository(db)
    s3 = MeetingBotS3()
    cid = new_correlation_id()
    status_field = f"{source.value}_mom_status"
    text_field = f"{source.value}_transcript_text"
    logger.info("[%s] %s MoM START for %s", cid, source.value, meeting_id)

    meeting = await repo.get_meeting(meeting_id)
    if not meeting:
        return
    text = meeting.get(text_field) or ""
    if not text.strip():
        # Rebuild from chunks if the flat field is missing.
        chunks = await repo.get_chunks(meeting_id, source.value, limit=100000)
        text = segments_to_text([
            {"start": c.get("start_time"), "speaker_label": c.get("speaker_name"), "text": c.get("text")}
            for c in chunks
        ])
    if not text.strip():
        await repo.update_meeting(meeting_id, {status_field: MomStatus.NOT_STARTED.value})
        logger.warning("[%s] no %s transcript to summarise", cid, source.value)
        return

    await repo.update_meeting(meeting_id, {status_field: MomStatus.GENERATING.value})
    await broker.publish(meeting_id, "status", {status_field: MomStatus.GENERATING.value})
    await _generate_and_save_mom(repo, s3, meeting_id, source, text, cid)


async def run_ai_mom(meeting_id: str, db) -> None:
    """Generate MoM from the AI-proofread transcript (uses corrected text)."""
    repo = MeetingBotRepository(db)
    s3 = MeetingBotS3()
    cid = new_correlation_id()
    logger.info("[%s] AI MoM START for %s", cid, meeting_id)

    meeting = await repo.get_meeting(meeting_id)
    if not meeting:
        return

    ai_chunks = await repo.get_chunks(meeting_id, Source.AI.value, limit=100000)
    if not ai_chunks:
        await repo.update_meeting(meeting_id, {"ai_mom_status": MomStatus.NOT_STARTED.value})
        logger.warning("[%s] no AI transcript chunks — run AI transcript first", cid)
        return

    lines = []
    for c in ai_chunks:
        text = c.get("corrected_text") or c.get("text", "")
        if text.strip():
            lines.append(
                f"[{_ts(c.get('start_time'))}] {c.get('speaker_name') or 'Unknown'}: {text}"
            )

    full_text = "\n".join(lines)
    if not full_text.strip():
        await repo.update_meeting(meeting_id, {"ai_mom_status": MomStatus.NOT_STARTED.value})
        return

    await repo.update_meeting(meeting_id, {"ai_mom_status": MomStatus.GENERATING.value})
    await broker.publish(meeting_id, "status", {"ai_mom_status": MomStatus.GENERATING.value})
    await _generate_and_save_mom(repo, s3, meeting_id, Source.AI, full_text, cid)


async def _generate_and_save_mom(repo, s3, meeting_id, source: Source, text: str, cid) -> None:
    status_field = f"{source.value}_mom_status"
    mom_field = f"{source.value}_mom"
    try:
        mom = await MomService().generate(text)
        await repo.save_mom(meeting_id, source.value, mom)
        import json

        await s3.upload_bytes(json.dumps(mom, default=str).encode(), f"mom_{source.value}", meeting_id, "application/json")
        await repo.update_meeting(meeting_id, {mom_field: mom, status_field: MomStatus.GENERATED.value})
        await broker.publish(meeting_id, "status", {status_field: MomStatus.GENERATED.value})
        logger.info("[%s] %s MoM generated", cid, source.value)
    except Exception as exc:  # noqa: BLE001 — isolated
        logger.exception("[%s] %s MoM generation FAILED", cid, source.value)
        await repo.update_meeting(meeting_id, {
            status_field: MomStatus.FAILED.value,
            f"{source.value}_mom_error": str(exc) or type(exc).__name__,
        })
        await broker.publish(meeting_id, "status", {status_field: MomStatus.FAILED.value})


def _ts(seconds) -> str:
    from app.meeting_bot.utils import fmt_timestamp

    return fmt_timestamp(seconds or 0)


def _cleanup(*paths: str) -> None:
    for p in paths:
        try:
            if p and os.path.exists(p):
                os.remove(p)
        except OSError:
            pass
