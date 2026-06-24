"""All ``/api/meeting-bot`` endpoints.

Self-contained router; does not touch the legacy ``/api/meetings`` routes.
Long-running operations run as FastAPI BackgroundTasks and are status-based.
"""
from __future__ import annotations

import hashlib
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.db.mongo import get_database
from app.meeting_bot import ai_transcript_service, processing, rag_service
from app.meeting_bot.translation_service import translate_transcript
from app.meeting_bot.live_events import broker
from app.meeting_bot.models import (
    BotStatus,
    MeetingStatus,
    MomStatus,
    RecordingStatus,
    Source,
    TranscriptStatus,
)
from app.meeting_bot.recall_service import (
    DONE_STATUSES,
    FAILED_STATUSES,
    JOINED_STATUSES,
    REMOVED_STATUSES,
    WAITING_STATUSES,
    MeetingBotRecall,
)
from app.meeting_bot.repository import MeetingBotRepository
from app.meeting_bot import schemas
from app.services.recall_service import RecallError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/meeting-bot", tags=["meeting-bot"])

# Language codes supported by the transcript translate endpoints.
_TRANSLATE_LANGS = {"hi", "en"}


def get_repo() -> MeetingBotRepository:
    return MeetingBotRepository(get_database())


# --------------------------------------------------------------------------- #
# Meetings
# --------------------------------------------------------------------------- #
@router.post("/meetings", response_model=schemas.MeetingCreated, status_code=201)
async def create_meeting(payload: schemas.MeetingCreate, repo: MeetingBotRepository = Depends(get_repo)):
    meeting = await repo.create_meeting({
        "meeting_title": payload.meeting_title,
        "meeting_link": payload.meeting_link,
        "participants": payload.participants or [],
        "created_by": payload.created_by,
        "num_speakers": payload.num_speakers,
    })
    mid = meeting["id"]
    logger.info("Meeting-bot meeting created: %s (%r)", mid, payload.meeting_title)

    try:
        bot = await MeetingBotRecall().create_bot(payload.meeting_link, payload.bot_name)
    except RecallError as exc:
        await repo.update_meeting(mid, {"status": MeetingStatus.FAILED.value, "error": str(exc)})
        raise HTTPException(status_code=502, detail=f"Recall.ai error: {exc}") from exc

    await repo.update_meeting(mid, {
        "bot_id": bot.get("id"),
        "status": MeetingStatus.JOINING.value,
        "bot_status": BotStatus.JOINING.value,
    })
    return schemas.MeetingCreated(meeting_id=mid, bot_id=bot.get("id"), status=MeetingStatus.JOINING.value)


@router.get("/meetings")
async def list_meetings(repo: MeetingBotRepository = Depends(get_repo)):
    return await repo.list_meetings()


@router.get("/meetings/{meeting_id}", response_model=schemas.MeetingDetail)
async def get_meeting(meeting_id: str, repo: MeetingBotRepository = Depends(get_repo)):
    meeting = await repo.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return _to_detail(meeting)


@router.post("/meetings/{meeting_id}/stop")
async def stop_meeting(meeting_id: str, repo: MeetingBotRepository = Depends(get_repo)):
    """Stop the meeting: make the bot leave, then finalize recordings + MoM.

    The bot leaves the call (recording is preserved), the meeting flips to
    'processing', and the poller finalizes (upload audio/video, transcript, MoM)
    as soon as the recording is ready.
    """
    meeting = await repo.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if meeting.get("status") in (MeetingStatus.COMPLETED.value, MeetingStatus.FAILED.value):
        raise HTTPException(status_code=400, detail="Meeting already ended")

    bot_id = meeting.get("bot_id")
    if bot_id:
        try:
            await MeetingBotRecall().leave_call(bot_id)
        except Exception as exc:  # noqa: BLE001 — proceed even if Recall errors
            logger.warning("stop: could not remove bot %s: %s", bot_id, exc)

    await repo.update_meeting(meeting_id, {
        "status": MeetingStatus.PROCESSING.value,
        "bot_status": BotStatus.LEFT.value,
        "recording_status": RecordingStatus.UPLOADING.value,
    })
    await broker.publish(meeting_id, "status", {"status": MeetingStatus.PROCESSING.value})
    logger.info("Meeting %s stopped by user; finalizing via poller.", meeting_id)
    return {"ok": True, "meeting_id": meeting_id, "status": MeetingStatus.PROCESSING.value}


@router.delete("/meetings/{meeting_id}", status_code=204)
async def delete_meeting(meeting_id: str, repo: MeetingBotRepository = Depends(get_repo)):
    meeting = await repo.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if meeting.get("bot_id"):
        try:
            await MeetingBotRecall().delete_bot(meeting["bot_id"])
        except Exception as exc:  # noqa: BLE001 — best effort
            logger.warning("delete bot failed: %s", exc)
    await repo.delete_meeting(meeting_id)


# --------------------------------------------------------------------------- #
# Transcripts & recordings & MoM (read)
# --------------------------------------------------------------------------- #
@router.get("/meetings/{meeting_id}/transcripts/{source}", response_model=schemas.TranscriptOut)
async def get_transcript(
    meeting_id: str,
    source: Source,
    skip: int = 0,
    limit: int = 1000,
    lang: str = "native",
    repo: MeetingBotRepository = Depends(get_repo),
):
    meeting = await repo.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    status = meeting.get(f"{source.value}_transcript_status") or (
        meeting.get("live_transcript_status") if source == Source.LIVE else TranscriptStatus.NOT_STARTED.value
    )
    chunks = await repo.get_chunks(meeting_id, source.value, skip=skip, limit=limit)
    total = await repo.count_chunks(meeting_id, source.value)
    text = meeting.get(f"{source.value}_transcript_text") or meeting.get("live_transcript_text", "")

    # Optional language filter: translate every line into Hindi / English.
    # Returns None for the native ("as spoken") view, which leaves text as-is.
    translated = None
    if (lang or "native").lower() not in ("native", "original", "as-spoken", ""):
        try:
            translated = await translate_transcript(meeting_id, source, lang, repo)
        except Exception:  # noqa: BLE001 — translation must never break viewing
            logger.exception("Transcript translation failed (lang=%s)", lang)
            translated = None

    out_chunks = []
    for i, c in enumerate(chunks):
        if translated is not None and (skip + i) < len(translated):
            c = {**c, "text": translated[skip + i]}
        out_chunks.append(_chunk_out(c, source))

    return schemas.TranscriptOut(
        meeting_id=meeting_id, source=source, status=status, text=text or "",
        chunks=out_chunks, total=total,
    )


@router.get("/meetings/{meeting_id}/recordings", response_model=schemas.RecordingsOut)
async def get_recordings(meeting_id: str, repo: MeetingBotRepository = Depends(get_repo)):
    meeting = await repo.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return schemas.RecordingsOut(
        meeting_id=meeting_id,
        audio_recording_url=meeting.get("audio_recording_url"),
        video_recording_url=meeting.get("video_recording_url"),
        audio_recording_status=meeting.get("audio_recording_status", RecordingStatus.NOT_STARTED.value),
        video_recording_status=meeting.get("video_recording_status", RecordingStatus.NOT_STARTED.value),
    )


@router.get("/meetings/{meeting_id}/mom/{source}", response_model=schemas.MomOut)
async def get_mom(meeting_id: str, source: Source, repo: MeetingBotRepository = Depends(get_repo)):
    meeting = await repo.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    mom = await repo.get_mom(meeting_id, source.value) or {}
    status = meeting.get(f"{source.value}_mom_status", MomStatus.NOT_STARTED.value)
    return schemas.MomOut(
        meeting_id=meeting_id, source=source, status=status,
        summary=mom.get("summary", ""),
        key_discussion_points=mom.get("key_discussion_points", []),
        decisions_taken=mom.get("decisions_taken", []),
        action_items=mom.get("action_items", []),
        pending_tasks=mom.get("pending_tasks", []),
        next_steps=mom.get("next_steps", []),
        speaker_wise_notes=mom.get("speaker_wise_notes", {}),
        generated_at=mom.get("generated_at"),
    )


# --------------------------------------------------------------------------- #
# Live events (SSE)
# --------------------------------------------------------------------------- #
@router.get("/meetings/{meeting_id}/events")
async def live_events(meeting_id: str):
    return StreamingResponse(
        broker.subscribe(meeting_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


# --------------------------------------------------------------------------- #
# Optional user-triggered jobs (audio / video transcribe + MoM)
# --------------------------------------------------------------------------- #
@router.post("/meetings/{meeting_id}/audio/transcribe", response_model=schemas.JobAccepted, status_code=202)
async def audio_transcribe(meeting_id: str, bg: BackgroundTasks, repo: MeetingBotRepository = Depends(get_repo)):
    return await _start_transcription(meeting_id, Source.AUDIO, bg, repo)


@router.post("/meetings/{meeting_id}/video/transcribe", response_model=schemas.JobAccepted, status_code=202)
async def video_transcribe(meeting_id: str, bg: BackgroundTasks, repo: MeetingBotRepository = Depends(get_repo)):
    return await _start_transcription(meeting_id, Source.VIDEO, bg, repo)


@router.post("/meetings/{meeting_id}/ai-transcript/generate", response_model=schemas.JobAccepted, status_code=202)
async def ai_transcript(meeting_id: str, bg: BackgroundTasks, repo: MeetingBotRepository = Depends(get_repo)):
    meeting = await repo.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if meeting.get("ai_transcript_status") == TranscriptStatus.GENERATING.value:
        return schemas.JobAccepted(meeting_id=meeting_id, job="ai_transcript", status="already_running")
    # Auto-generate audio transcript first if not already done, then AI proofreading.
    bg.add_task(_run_ai_transcript_pipeline, meeting_id, get_database())
    return schemas.JobAccepted(meeting_id=meeting_id, job="ai_transcript", status="started")


async def _run_ai_transcript_pipeline(meeting_id: str, db) -> None:
    """Generate audio transcript (if missing) then run AI proofreading."""
    repo = MeetingBotRepository(db)
    meeting = await repo.get_meeting(meeting_id)
    if not meeting:
        return
    if meeting.get("audio_transcript_status") != TranscriptStatus.GENERATED.value:
        await processing.run_media_transcription(meeting_id, Source.AUDIO, db)
        meeting = await repo.get_meeting(meeting_id)
        if (meeting or {}).get("audio_transcript_status") != TranscriptStatus.GENERATED.value:
            return  # audio transcription failed — stop here
    await ai_transcript_service.generate_ai_transcript(meeting_id, db)


@router.post("/meetings/{meeting_id}/audio/generate-mom", response_model=schemas.JobAccepted, status_code=202)
async def audio_mom(meeting_id: str, bg: BackgroundTasks, repo: MeetingBotRepository = Depends(get_repo)):
    meeting = await repo.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if meeting.get("audio_mom_status") == MomStatus.GENERATING.value:
        return schemas.JobAccepted(meeting_id=meeting_id, job="audio_mom", status="already_running")
    bg.add_task(_run_audio_mom_pipeline, meeting_id, get_database())
    return schemas.JobAccepted(meeting_id=meeting_id, job="audio_mom", status="started")


async def _run_audio_mom_pipeline(meeting_id: str, db) -> None:
    """Generate audio transcript (if missing) then generate MoM."""
    repo = MeetingBotRepository(db)
    meeting = await repo.get_meeting(meeting_id)
    if not meeting:
        return
    if meeting.get("audio_transcript_status") != TranscriptStatus.GENERATED.value:
        await processing.run_media_transcription(meeting_id, Source.AUDIO, db)
        meeting = await repo.get_meeting(meeting_id)
        if (meeting or {}).get("audio_transcript_status") != TranscriptStatus.GENERATED.value:
            return  # transcription failed — stop
    await processing.run_source_mom(meeting_id, Source.AUDIO, db)


@router.post("/meetings/{meeting_id}/video/generate-mom", response_model=schemas.JobAccepted, status_code=202)
async def video_mom(meeting_id: str, bg: BackgroundTasks, repo: MeetingBotRepository = Depends(get_repo)):
    return await _start_mom(meeting_id, Source.VIDEO, bg, repo)


async def _start_transcription(meeting_id, source: Source, bg, repo) -> schemas.JobAccepted:
    meeting = await repo.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    field = f"{source.value}_transcript_status"
    if meeting.get(field) == TranscriptStatus.GENERATING.value:
        return schemas.JobAccepted(meeting_id=meeting_id, job=f"{source.value}_transcribe", status="already_running")
    bg.add_task(processing.run_media_transcription, meeting_id, source, get_database())
    return schemas.JobAccepted(meeting_id=meeting_id, job=f"{source.value}_transcribe", status="started")


async def _start_mom(meeting_id, source: Source, bg, repo) -> schemas.JobAccepted:
    meeting = await repo.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if meeting.get(f"{source.value}_transcript_status") != TranscriptStatus.GENERATED.value:
        raise HTTPException(status_code=400, detail=f"{source.value} transcript not generated yet")
    if meeting.get(f"{source.value}_mom_status") == MomStatus.GENERATING.value:
        return schemas.JobAccepted(meeting_id=meeting_id, job=f"{source.value}_mom", status="already_running")
    bg.add_task(processing.run_source_mom, meeting_id, source, get_database())
    return schemas.JobAccepted(meeting_id=meeting_id, job=f"{source.value}_mom", status="started")


# --------------------------------------------------------------------------- #
# Embeddings + Ask (semantic search / Q&A over the transcripts)
# --------------------------------------------------------------------------- #
@router.post("/meetings/{meeting_id}/embeddings", response_model=schemas.JobAccepted, status_code=202)
async def generate_embeddings(meeting_id: str, bg: BackgroundTasks, repo: MeetingBotRepository = Depends(get_repo)):
    meeting = await repo.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if meeting.get("embeddings_status") == TranscriptStatus.GENERATING.value:
        return schemas.JobAccepted(meeting_id=meeting_id, job="embeddings", status="already_running")
    bg.add_task(rag_service.generate_embeddings, meeting_id, get_database())
    return schemas.JobAccepted(meeting_id=meeting_id, job="embeddings", status="started")


@router.post("/meetings/{meeting_id}/ask", response_model=schemas.AskResponse)
async def ask_meeting(meeting_id: str, payload: schemas.AskRequest, repo: MeetingBotRepository = Depends(get_repo)):
    meeting = await repo.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    result = await rag_service.ask(meeting_id, payload.question, get_database(), top_k=payload.top_k)
    return schemas.AskResponse(
        meeting_id=meeting_id, question=payload.question,
        answer=result["answer"], sources=result["sources"],
    )


# --------------------------------------------------------------------------- #
# Live MoM (user-triggered from the single-page dashboard)
# --------------------------------------------------------------------------- #
@router.post("/meetings/{meeting_id}/live/generate-mom", response_model=schemas.JobAccepted, status_code=202)
async def live_mom(meeting_id: str, bg: BackgroundTasks, repo: MeetingBotRepository = Depends(get_repo)):
    return await _start_mom(meeting_id, Source.LIVE, bg, repo)


# --------------------------------------------------------------------------- #
# Per-source Ask (audio / video — filters embedded chunks by source)
# --------------------------------------------------------------------------- #
@router.post("/meetings/{meeting_id}/audio/ask", response_model=schemas.AskResponse)
async def ask_audio(meeting_id: str, payload: schemas.AskRequest, repo: MeetingBotRepository = Depends(get_repo)):
    meeting = await repo.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    result = await rag_service.ask(meeting_id, payload.question, get_database(), top_k=payload.top_k, source_filter=Source.AUDIO.value)
    return schemas.AskResponse(meeting_id=meeting_id, question=payload.question, answer=result["answer"], sources=result["sources"])


@router.post("/meetings/{meeting_id}/video/ask", response_model=schemas.AskResponse)
async def ask_video(meeting_id: str, payload: schemas.AskRequest, repo: MeetingBotRepository = Depends(get_repo)):
    meeting = await repo.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    result = await rag_service.ask(meeting_id, payload.question, get_database(), top_k=payload.top_k, source_filter=Source.VIDEO.value)
    return schemas.AskResponse(meeting_id=meeting_id, question=payload.question, answer=result["answer"], sources=result["sources"])


# --------------------------------------------------------------------------- #
# Transcript translation  (POST → translated chunks cached in MongoDB)
# --------------------------------------------------------------------------- #
@router.post("/meetings/{meeting_id}/audio/transcript/translate", response_model=schemas.TranslateResponse)
async def translate_audio_transcript(
    meeting_id: str,
    payload: schemas.TranslateRequest,
    repo: MeetingBotRepository = Depends(get_repo),
):
    """Translate audio transcript to Hindi ('hi') or English ('en').

    Results are cached on the meeting document; subsequent calls for the same
    language return immediately without calling the LLM again.
    """
    if payload.target_language not in _TRANSLATE_LANGS:
        raise HTTPException(400, detail=f"Unsupported language '{payload.target_language}'. Use: {sorted(_TRANSLATE_LANGS)}")
    return await _do_translate(meeting_id, Source.AUDIO, payload.target_language, repo)


@router.post("/meetings/{meeting_id}/video/transcript/translate", response_model=schemas.TranslateResponse)
async def translate_video_transcript(
    meeting_id: str,
    payload: schemas.TranslateRequest,
    repo: MeetingBotRepository = Depends(get_repo),
):
    """Translate video transcript to Hindi ('hi') or English ('en')."""
    if payload.target_language not in _TRANSLATE_LANGS:
        raise HTTPException(400, detail=f"Unsupported language '{payload.target_language}'. Use: {sorted(_TRANSLATE_LANGS)}")
    return await _do_translate(meeting_id, Source.VIDEO, payload.target_language, repo)


async def _do_translate(
    meeting_id: str, source: Source, lang: str, repo: MeetingBotRepository
) -> schemas.TranslateResponse:
    meeting = await repo.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    chunks = await repo.get_chunks(meeting_id, source.value, limit=100000)
    if not chunks:
        return schemas.TranslateResponse(meeting_id=meeting_id, source=source, lang=lang, chunks=[])

    # translate_transcript returns a list of translated texts aligned to chunks,
    # or None for native/unsupported languages. Results are cached in MongoDB.
    translated = await translate_transcript(meeting_id, source, lang, repo)

    out = []
    for i, c in enumerate(chunks):
        if translated and i < len(translated) and translated[i]:
            c = {**c, "text": translated[i]}
        out.append(_chunk_out(c, source))

    return schemas.TranslateResponse(meeting_id=meeting_id, source=source, lang=lang, chunks=out)


# --------------------------------------------------------------------------- #
# Webhooks
# --------------------------------------------------------------------------- #
@router.post("/webhooks/recall")
async def recall_status_webhook(
    request: Request,
    bg: BackgroundTasks,
    x_recall_signature: str | None = Header(default=None),
    repo: MeetingBotRepository = Depends(get_repo),
):
    raw = await request.body()
    if not MeetingBotRecall.verify_webhook(raw, x_recall_signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    payload = await request.json()
    ev = MeetingBotRecall.parse_status_event(payload)
    bot_id, code = ev["bot_id"], ev["status_code"]
    if not bot_id:
        return {"ok": True, "ignored": "no bot_id"}
    if await repo.seen_webhook(ev["event_id"]):
        return {"ok": True, "duplicate": True}

    meeting = await repo.get_meeting_by_bot(bot_id)
    if not meeting:
        return {"ok": True, "ignored": "unknown bot"}
    mid = meeting["id"]
    logger.info("MB status webhook: bot=%s code=%s", bot_id, code)

    updates = _status_to_updates(code)
    if updates:
        await repo.update_meeting(mid, updates)
        await broker.publish(mid, "status", updates)

    if code in DONE_STATUSES or ev["event"] in {"bot.done", "recording.done"}:
        await repo.update_meeting(mid, {"recording_status": RecordingStatus.UPLOADING.value})
        bg.add_task(processing.finalize_meeting, mid, get_database())
    return {"ok": True}


@router.post("/webhooks/recall/transcript")
async def recall_transcript_webhook(request: Request, repo: MeetingBotRepository = Depends(get_repo)):
    raw = await request.body()
    payload = await request.json()
    chunk = MeetingBotRecall.parse_transcript_event(payload)
    if not chunk or not chunk.get("bot_id"):
        return {"ok": True, "ignored": "no transcript"}
    meeting = await repo.get_meeting_by_bot(chunk["bot_id"])
    if not meeting:
        return {"ok": True, "ignored": "unknown bot"}
    mid = meeting["id"]

    # Stable id so re-delivered chunks de-duplicate.
    basis = f"{mid}:live:{chunk.get('start_time')}:{chunk['text']}"
    chunk_id = hashlib.sha256(basis.encode()).hexdigest()[:24]
    doc = {
        "chunk_id": chunk_id, "meeting_id": mid, "bot_id": chunk["bot_id"], "source": Source.LIVE.value,
        "speaker_name": chunk.get("speaker_name"), "start_time": chunk.get("start_time"),
        "end_time": chunk.get("end_time"), "text": chunk["text"], "is_final": chunk.get("is_final", True),
        "chunk_index": int((chunk.get("start_time") or 0) * 1000),
    }
    inserted = await repo.add_chunk(doc)
    if meeting.get("live_transcript_status") in (None, TranscriptStatus.NOT_STARTED.value):
        await repo.update_meeting(mid, {
            "live_transcript_status": TranscriptStatus.GENERATING.value,
            "status": MeetingStatus.LIVE.value,
        })
    if inserted or not chunk.get("is_final", True):
        await broker.publish(mid, "transcript", _chunk_event(doc))
    return {"ok": True, "duplicate": not inserted}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _status_to_updates(code: str | None) -> dict:
    if not code:
        return {}
    if code in JOINED_STATUSES:
        return {
            "bot_status": BotStatus.JOINED.value, "status": MeetingStatus.LIVE.value,
            "recording_status": RecordingStatus.RECORDING.value,
            "audio_recording_status": RecordingStatus.RECORDING.value,
            "video_recording_status": RecordingStatus.RECORDING.value,
            "live_transcript_status": TranscriptStatus.GENERATING.value,
        }
    if code in WAITING_STATUSES:
        return {"bot_status": BotStatus.WAITING.value, "status": MeetingStatus.WAITING_FOR_ADMIT.value}
    if code in FAILED_STATUSES:
        return {"bot_status": BotStatus.FAILED.value, "status": MeetingStatus.FAILED.value}
    if code in REMOVED_STATUSES:
        return {"bot_status": BotStatus.REMOVED.value}
    return {}


def _to_detail(m: dict) -> schemas.MeetingDetail:
    completed = m.get("status") == MeetingStatus.COMPLETED.value
    audio_ready = m.get("audio_recording_status") in (RecordingStatus.UPLOADED.value, RecordingStatus.FAILED.value)
    video_ready = m.get("video_recording_status") in (RecordingStatus.UPLOADED.value, RecordingStatus.FAILED.value)
    actions = schemas.ActionState(
        can_generate_live_mom=m.get("live_transcript_status") == TranscriptStatus.GENERATED.value
        and m.get("live_mom_status") != MomStatus.GENERATING.value,
        can_generate_audio_transcript=completed and audio_ready
        and m.get("audio_transcript_status") != TranscriptStatus.GENERATING.value,
        can_generate_ai_transcript=completed and audio_ready
        and m.get("ai_transcript_status") != TranscriptStatus.GENERATING.value,
        can_generate_audio_mom=completed and audio_ready
        and m.get("audio_mom_status") != MomStatus.GENERATING.value,
        can_generate_video_transcript=completed and video_ready
        and m.get("video_transcript_status") != TranscriptStatus.GENERATING.value,
        can_generate_video_mom=m.get("video_transcript_status") == TranscriptStatus.GENERATED.value
        and m.get("video_mom_status") != MomStatus.GENERATING.value,
    )
    return schemas.MeetingDetail(
        meeting_id=m["id"], meeting_title=m.get("meeting_title", ""), meeting_link=m.get("meeting_link"),
        created_by=m.get("created_by"), bot_id=m.get("bot_id"),
        status=m.get("status", MeetingStatus.CREATED.value),
        bot_status=m.get("bot_status", BotStatus.NOT_JOINED.value),
        live_transcript_status=m.get("live_transcript_status", TranscriptStatus.NOT_STARTED.value),
        recording_status=m.get("recording_status", RecordingStatus.NOT_STARTED.value),
        audio_recording_status=m.get("audio_recording_status", RecordingStatus.NOT_STARTED.value),
        video_recording_status=m.get("video_recording_status", RecordingStatus.NOT_STARTED.value),
        live_mom_status=m.get("live_mom_status", MomStatus.NOT_STARTED.value),
        audio_transcript_status=m.get("audio_transcript_status", TranscriptStatus.NOT_STARTED.value),
        ai_transcript_status=m.get("ai_transcript_status", TranscriptStatus.NOT_STARTED.value),
        audio_mom_status=m.get("audio_mom_status", MomStatus.NOT_STARTED.value),
        video_transcript_status=m.get("video_transcript_status", TranscriptStatus.NOT_STARTED.value),
        video_mom_status=m.get("video_mom_status", MomStatus.NOT_STARTED.value),
        audio_recording_url=m.get("audio_recording_url"), video_recording_url=m.get("video_recording_url"),
        embeddings_status=m.get("embeddings_status", "not_started"),
        embedded_chunks=m.get("embedded_chunks", 0),
        audio_transcript_language=m.get("audio_transcript_language"),
        video_transcript_language=m.get("video_transcript_language"),
        error=m.get("error"), available_actions=actions,
        created_at=m.get("created_at"), updated_at=m.get("updated_at"), completed_at=m.get("completed_at"),
    )


def _chunk_out(c: dict, source: Source) -> schemas.TranscriptChunkOut:
    return schemas.TranscriptChunkOut(
        chunk_id=c.get("chunk_id", ""), meeting_id=c.get("meeting_id", ""), source=source,
        speaker_name=c.get("speaker_name"), start_time=c.get("start_time"), end_time=c.get("end_time"),
        text=c.get("text", ""), corrected_text=c.get("corrected_text"),
        corrections=c.get("corrections", []),
        is_final=c.get("is_final", True), chunk_index=c.get("chunk_index", 0),
        created_at=c.get("created_at"),
    )


def _chunk_event(c: dict) -> dict:
    return {
        "speaker_name": c.get("speaker_name") or "Unknown", "start_time": c.get("start_time"),
        "text": c.get("text"), "is_final": c.get("is_final", True),
    }
