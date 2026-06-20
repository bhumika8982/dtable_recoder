"""Background poller that triggers the pipeline without a public webhook.

Recall.ai delivers a ``bot.done`` webhook when a recording is ready, but that
webhook can't reach a backend running on ``localhost``. To make local
development work end-to-end, this poller periodically asks Recall about each
meeting that is still waiting to be processed and, once the recording is
available, runs :func:`process_meeting` itself.

It is started/stopped from the FastAPI lifespan. Single process, so an in-memory
``_inflight`` set is enough to guarantee a meeting is never processed twice.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from app.config import settings
from app.db.mongo import get_database
from app.models.enums import MeetingStatus
from app.repositories.meeting_repo import MeetingRepository
from app.services.processing import process_meeting
from app.services.recall_service import RecallError, RecallService

logger = logging.getLogger(__name__)

# Statuses where the bot exists but processing hasn't been kicked off yet.
_WAITING = {
    MeetingStatus.CREATED.value,
    MeetingStatus.BOT_SCHEDULED.value,
    MeetingStatus.IN_CALL.value,
    MeetingStatus.RECORDING_READY.value,
}

# Mid-pipeline statuses. A process restart kills in-flight work, so on startup
# we reset these back to RECORDING_READY and let the poller resume them.
_ACTIVE = {
    MeetingStatus.DOWNLOADING.value,
    MeetingStatus.EXTRACTING_AUDIO.value,
    MeetingStatus.TRANSCRIBING.value,
    MeetingStatus.DIARIZING.value,
    MeetingStatus.MERGING.value,
    MeetingStatus.GENERATING_MOM.value,
}

# Map Recall bot status codes -> our intermediate UI status (best effort).
_RECALL_STATUS_MAP = {
    "in_call_recording": MeetingStatus.IN_CALL,
    "in_call_not_recording": MeetingStatus.IN_CALL,
}


class RecallPoller:
    def __init__(self, interval_seconds: int = 20):
        self.interval = interval_seconds
        self._task: Optional[asyncio.Task] = None
        # Created in start() so it binds to the running loop (not import time).
        self._stop: Optional[asyncio.Event] = None
        self._inflight: set[str] = set()

    def start(self) -> None:
        if not settings.recall_api_key:
            logger.warning("Recall poller NOT started: RECALL_API_KEY is not set.")
            return
        if self._task is not None:
            return
        self._stop = asyncio.Event()
        self._task = asyncio.create_task(self._run())
        logger.info("Recall poller started (interval=%ss).", self.interval)

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
            logger.info("Recall poller stopped.")

    async def _run(self) -> None:
        await self._recover_interrupted()
        while not self._stop.is_set():
            try:
                await self._tick()
            except Exception:  # noqa: BLE001 — never let the loop die
                logger.exception("Recall poller tick failed.")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval)
            except asyncio.TimeoutError:
                pass

    async def _recover_interrupted(self) -> None:
        """Reset meetings left mid-pipeline by a previous run so they re-process."""
        db = get_database()
        repo = MeetingRepository(db)
        stale = [m for m in await repo.list(limit=200) if m.get("status") in _ACTIVE]
        for m in stale:
            logger.warning(
                "Recovering interrupted meeting %s (was %s) -> recording_ready.",
                m["id"],
                m.get("status"),
            )
            await repo.set_status(m["id"], MeetingStatus.RECORDING_READY)

    async def _tick(self) -> None:
        db = get_database()
        repo = MeetingRepository(db)
        recall = RecallService()

        candidates = [
            m
            for m in await repo.list(limit=200)
            if m.get("status") in _WAITING and m.get("recall_bot_id")
        ]
        if not candidates:
            return
        logger.debug("Poller checking %d waiting meeting(s).", len(candidates))

        for m in candidates:
            mid = m["id"]
            bot_id = m["recall_bot_id"]
            if mid in self._inflight:
                continue
            try:
                bot = await recall.get_bot(bot_id)
            except RecallError as exc:
                logger.error("Poller: Recall lookup failed for bot %s: %s", bot_id, exc)
                continue

            await self._sync_intermediate_status(repo, m, bot)

            recording_url = recall.extract_recording_url(bot)
            if not recording_url:
                continue  # not ready yet

            # Process one meeting at a time. WhisperX/pyannote are CPU/RAM heavy;
            # running several concurrently would exhaust resources.
            if self._inflight:
                logger.info(
                    "Poller: meeting %s ready but another is processing; will pick up next tick.",
                    mid,
                )
                break

            logger.info(
                "Poller: recording READY for meeting %s (bot %s). Triggering pipeline.",
                mid,
                bot_id,
            )
            self._inflight.add(mid)
            asyncio.create_task(self._process(mid, db))
            break

    async def _process(self, meeting_id: str, db) -> None:
        try:
            await process_meeting(meeting_id, db)
        finally:
            self._inflight.discard(meeting_id)

    async def _sync_intermediate_status(self, repo, meeting, bot) -> None:
        """Reflect 'bot joined' / 'recording started' in the UI status."""
        changes = bot.get("status_changes") or []
        latest = changes[-1].get("code") if changes else None
        mapped = _RECALL_STATUS_MAP.get(latest)
        if mapped and meeting.get("status") != mapped.value:
            if latest == "in_call_recording":
                logger.info("Bot joined & recording STARTED for meeting %s.", meeting["id"])
            await repo.set_status(meeting["id"], mapped)


# Module-level singleton managed by the app lifespan.
poller = RecallPoller()
