"""Recall.ai webhook receiver.

Recall calls this when a bot's status changes. When the recording is ready
(``bot.done`` / status_change to ``done``), we kick off the processing pipeline
as a FastAPI BackgroundTask — no queue involved.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request

from app.deps import get_db, get_meeting_repo
from app.models.enums import MeetingStatus
from app.repositories.meeting_repo import MeetingRepository
from app.services.processing import process_meeting
from app.services.recall_service import RecallService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

# Recall events that indicate the recording is finished and downloadable.
_DONE_EVENTS = {"bot.done", "bot.recording_done", "recording.done"}
_DONE_STATUSES = {"done", "recording_done", "call_ended"}


@router.post("/recall")
async def recall_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_recall_signature: str | None = Header(default=None),
    repo: MeetingRepository = Depends(get_meeting_repo),
    db=Depends(get_db),
):
    raw = await request.body()
    if not RecallService.verify_webhook(raw, x_recall_signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    payload = await request.json()
    event = payload.get("event", "")
    data = payload.get("data", {}) or {}
    bot_id = data.get("bot_id") or (data.get("bot") or {}).get("id") or payload.get("bot_id")
    status_code = (data.get("status") or {}).get("code") if isinstance(data.get("status"), dict) else data.get("status")
    logger.info("Webhook received: event=%r status=%r bot_id=%s", event, status_code, bot_id)

    if not bot_id:
        return {"ok": True, "ignored": "no bot_id"}

    meeting = await repo.get_by_bot_id(bot_id)
    if not meeting:
        logger.warning("Webhook for unknown bot_id=%s — ignored.", bot_id)
        return {"ok": True, "ignored": "unknown bot"}

    # Reflect intermediate states for the UI.
    if status_code == "in_call_recording":
        logger.info("Bot joined & recording STARTED for meeting %s.", meeting["id"])
        await repo.set_status(meeting["id"], MeetingStatus.IN_CALL)

    if event in _DONE_EVENTS or status_code in _DONE_STATUSES:
        logger.info("Recording DONE webhook for meeting %s — scheduling pipeline.", meeting["id"])
        await repo.set_status(meeting["id"], MeetingStatus.RECORDING_READY)
        background_tasks.add_task(process_meeting, meeting["id"], db)
        return {"ok": True, "processing": meeting["id"]}

    return {"ok": True, "event": event}
