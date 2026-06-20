"""Status poller for the advanced meeting-bot flow (no public webhook needed).

The advanced flow normally updates status from Recall webhooks, but those can't
reach a ``localhost`` server. This poller asks Recall about each active bot every
few seconds and:

  * reflects bot/recording status in the UI (joining -> joined -> recording),
  * when the call ends and the recording is ready, runs ``finalize_meeting``
    (upload audio/video to S3, live MoM from any captured live transcript).

Mirrors the legacy ``app.services.poller_service`` but for the ``mb_*``
collections. Single process, so an in-memory ``_inflight`` set is enough.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from app.config import settings
from app.db.mongo import get_database
from app.meeting_bot import processing
from app.meeting_bot.live_events import broker
from app.meeting_bot.models import (
    BotStatus,
    MeetingStatus,
    RecordingStatus,
    TranscriptStatus,
)
from app.meeting_bot.recall_service import (
    DONE_STATUSES,
    FAILED_STATUSES,
    JOINED_STATUSES,
    WAITING_STATUSES,
    MeetingBotRecall,
)
from app.meeting_bot.repository import MeetingBotRepository

logger = logging.getLogger(__name__)

# Meeting statuses where the bot exists and we should keep polling.
# PROCESSING is included so a meeting that ended (but whose finalize hasn't
# completed yet) keeps being picked up until it reaches completed/failed.
_ACTIVE = {
    MeetingStatus.CREATED.value,
    MeetingStatus.JOINING.value,
    MeetingStatus.WAITING_FOR_ADMIT.value,
    MeetingStatus.LIVE.value,
    MeetingStatus.PROCESSING.value,
}


class MeetingBotPoller:
    def __init__(self, interval_seconds: int = 15):
        self.interval = interval_seconds
        self._task: Optional[asyncio.Task] = None
        self._stop: Optional[asyncio.Event] = None
        self._inflight: set[str] = set()

    def start(self) -> None:
        if not settings.recall_api_key:
            logger.warning("Meeting-bot poller NOT started: RECALL_API_KEY missing.")
            return
        if self._task is not None:
            return
        self._stop = asyncio.Event()
        self._task = asyncio.create_task(self._run())
        logger.info("Meeting-bot poller started (interval=%ss).", self.interval)

    async def stop(self) -> None:
        if self._stop is not None:
            self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
            logger.info("Meeting-bot poller stopped.")

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self._tick()
            except Exception:  # noqa: BLE001 — never let the loop die
                logger.exception("Meeting-bot poller tick failed.")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval)
            except asyncio.TimeoutError:
                pass

    async def _tick(self) -> None:
        db = get_database()
        repo = MeetingBotRepository(db)
        recall = MeetingBotRecall()

        candidates = [
            m for m in await repo.list_meetings(limit=200)
            if m.get("status") in _ACTIVE and m.get("bot_id")
        ]
        for m in candidates:
            mid, bot_id = m["id"], m["bot_id"]
            try:
                bot = await recall.get_bot(bot_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Poller: Recall lookup failed for bot %s: %s", bot_id, exc)
                continue

            latest = _latest_code(bot)
            await self._apply_status(repo, m, latest, mid)

            # Call ended -> immediately flip the UI to "processing" so the user
            # sees "meeting ended, preparing…" the moment they leave the call.
            call_ended = latest in DONE_STATUSES
            if call_ended and m.get("status") not in (
                MeetingStatus.PROCESSING.value, MeetingStatus.COMPLETED.value,
            ):
                await repo.update_meeting(mid, {
                    "status": MeetingStatus.PROCESSING.value,
                    "bot_status": BotStatus.LEFT.value,
                    "recording_status": RecordingStatus.UPLOADING.value,
                })
                await broker.publish(mid, "status", {"status": MeetingStatus.PROCESSING.value})

            # Recording ready -> finalize (upload + transcript + MoM), once.
            ready = call_ended or bool(_has_recording(bot))
            if ready and mid not in self._inflight:
                if self._inflight:
                    # One heavy finalize at a time (downloads + transcode).
                    continue
                logger.info("Poller: recording READY for meeting %s — finalizing.", mid)
                self._inflight.add(mid)
                asyncio.create_task(self._finalize(mid, db))

    async def _apply_status(self, repo, meeting, code, mid) -> None:
        if not code:
            return
        updates = {}
        if code in JOINED_STATUSES:
            if meeting.get("status") != MeetingStatus.LIVE.value:
                logger.info("Poller: bot JOINED & recording for meeting %s.", mid)
            updates = {
                "bot_status": BotStatus.JOINED.value,
                "status": MeetingStatus.LIVE.value,
                "recording_status": RecordingStatus.RECORDING.value,
                "audio_recording_status": RecordingStatus.RECORDING.value,
                "video_recording_status": RecordingStatus.RECORDING.value,
            }
        elif code in WAITING_STATUSES:
            updates = {
                "bot_status": BotStatus.WAITING.value,
                "status": MeetingStatus.WAITING_FOR_ADMIT.value,
            }
        elif code in FAILED_STATUSES:
            updates = {"bot_status": BotStatus.FAILED.value, "status": MeetingStatus.FAILED.value}

        # Only write if something actually changed (avoid churn).
        changed = {k: v for k, v in updates.items() if meeting.get(k) != v}
        if changed:
            await repo.update_meeting(mid, changed)
            await broker.publish(mid, "status", changed)

    async def _finalize(self, meeting_id: str, db) -> None:
        try:
            await processing.finalize_meeting(meeting_id, db)
        finally:
            self._inflight.discard(meeting_id)


def _latest_code(bot: dict) -> Optional[str]:
    changes = bot.get("status_changes") or []
    if changes:
        return changes[-1].get("code")
    status = bot.get("status")
    return status.get("code") if isinstance(status, dict) else status


def _has_recording(bot: dict) -> bool:
    for rec in bot.get("recordings") or []:
        media = rec.get("media_shortcuts") or {}
        for name in ("video_mixed", "audio_mixed"):
            data = (media.get(name) or {}).get("data") or {}
            if data.get("download_url"):
                return True
    return False


# Module-level singleton managed by the app lifespan.
mb_poller = MeetingBotPoller()
