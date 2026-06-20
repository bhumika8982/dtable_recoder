"""Meeting CRUD + Recall bot dispatch + results retrieval."""
from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.deps import get_db, get_meeting_repo
from app.models.enums import MeetingStatus
from app.repositories.meeting_repo import MeetingRepository
from app.schemas.meeting import MeetingCreate, MomOut, TranscriptOut
from app.services.processing import process_meeting
from app.services.recall_service import RecallError, RecallService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/meetings", tags=["meetings"])


@router.post("", status_code=201)
async def create_meeting(
    payload: MeetingCreate, repo: MeetingRepository = Depends(get_meeting_repo)
):
    """Create a meeting and dispatch a Recall.ai bot to join + record it."""
    meeting = await repo.create(payload.model_dump())
    logger.info("Meeting created: id=%s title=%r.", meeting["id"], payload.title)

    recall = RecallService()
    try:
        bot = await recall.create_bot(
            meeting_url=payload.meeting_url,
            bot_name=payload.bot_name,
            join_at=payload.join_at.isoformat() if payload.join_at else None,
        )
    except RecallError as exc:
        await repo.set_status(meeting["id"], MeetingStatus.FAILED, error=str(exc))
        raise HTTPException(status_code=502, detail=f"Recall.ai error: {exc}") from exc

    await repo.update(
        meeting["id"],
        {"recall_bot_id": bot.get("id"), "status": MeetingStatus.BOT_SCHEDULED.value},
    )
    logger.info(
        "Bot dispatched for meeting %s (bot_id=%s). Poller will process when recording is ready.",
        meeting["id"],
        bot.get("id"),
    )
    return await repo.get(meeting["id"])


@router.get("")
async def list_meetings(repo: MeetingRepository = Depends(get_meeting_repo)):
    return await repo.list()


@router.get("/{meeting_id}")
async def get_meeting(meeting_id: str, repo: MeetingRepository = Depends(get_meeting_repo)):
    meeting = await repo.get(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return meeting


@router.delete("/{meeting_id}", status_code=204)
async def delete_meeting(
    meeting_id: str, repo: MeetingRepository = Depends(get_meeting_repo)
):
    """Delete a meeting and its transcript/MOM. Best-effort: also stops the Recall bot."""
    meeting = await repo.get(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    # Best-effort: tell Recall to remove the bot. Never block deletion on this.
    bot_id = meeting.get("recall_bot_id")
    if bot_id:
        try:
            await RecallService().delete_bot(bot_id)
        except Exception as exc:  # noqa: BLE001 — bot may already be gone
            logger.warning("Could not delete Recall bot %s: %s", bot_id, exc)

    await repo.delete(meeting_id)
    logger.info("Meeting %s deleted.", meeting_id)


@router.get("/{meeting_id}/transcript", response_model=TranscriptOut)
async def get_transcript(meeting_id: str, repo: MeetingRepository = Depends(get_meeting_repo)):
    doc = await repo.get_transcript(meeting_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Transcript not ready")
    return TranscriptOut(meeting_id=meeting_id, **{k: doc[k] for k in ("language", "segments", "full_text", "formatted") if k in doc})


@router.get("/{meeting_id}/mom", response_model=MomOut)
async def get_mom(meeting_id: str, repo: MeetingRepository = Depends(get_meeting_repo)):
    doc = await repo.get_mom(meeting_id)
    if not doc:
        raise HTTPException(status_code=404, detail="MOM not ready")
    return MomOut(
        meeting_id=meeting_id,
        summary=doc.get("summary", ""),
        key_points=doc.get("key_points", []),
        action_items=doc.get("action_items", []),
        next_steps=doc.get("next_steps", []),
        attendees=doc.get("attendees", []),
    )


@router.post("/{meeting_id}/process", status_code=202)
async def trigger_processing(
    meeting_id: str,
    background_tasks: BackgroundTasks,
    repo: MeetingRepository = Depends(get_meeting_repo),
    db=Depends(get_db),
):
    """Manually (re)trigger the processing pipeline for a meeting.

    Normally this fires automatically from the Recall webhook, but this endpoint
    is useful for retries or local testing.
    """
    meeting = await repo.get(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if not meeting.get("recall_bot_id"):
        raise HTTPException(status_code=400, detail="Meeting has no Recall bot.")
    background_tasks.add_task(process_meeting, meeting_id, db)
    return {"status": "processing_started", "meeting_id": meeting_id}
