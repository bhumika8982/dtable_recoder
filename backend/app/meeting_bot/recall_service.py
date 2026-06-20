"""Recall.ai integration for the meeting-bot flow.

Builds on the existing ``app.services.recall_service.RecallService`` (auth,
requests, recording-url + speaker-timeline parsing) and adds:

  * bot creation configured for audio + video recording, real-time transcript
    (meeting captions) and participant events (real speaker names);
  * normalised webhook event parsing;
  * separate audio / video download-url extraction.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.config import settings
from app.services.recall_service import RecallError, RecallService

logger = logging.getLogger(__name__)


def _is_public_url(url: str) -> bool:
    """True only for an http(s) URL Recall can reach (not localhost/private)."""
    if not url or not url.lower().startswith(("http://", "https://")):
        return False
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False
    blocked = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
    if host in blocked or host.endswith(".local"):
        return False
    # Common private ranges.
    if host.startswith(("10.", "192.168.", "169.254.")) or host.startswith("172."):
        return False
    return True


# Recall status codes that mean the call ended / recording is ready.
DONE_STATUSES = {"done", "recording_done", "call_ended", "recording.done"}
JOINING_STATUSES = {"joining_call", "in_waiting_room"}
WAITING_STATUSES = {"in_waiting_room", "waiting_for_host"}
JOINED_STATUSES = {"in_call_recording", "in_call_not_recording", "recording_permission_allowed"}
FAILED_STATUSES = {"fatal", "bot_rejected", "recording_permission_denied"}
REMOVED_STATUSES = {"call_ended_by_host", "bot_removed", "removed"}


class MeetingBotRecall:
    def __init__(self) -> None:
        self._recall = RecallService()

    # ------------------------------------------------------------------ #
    # Bot creation
    # ------------------------------------------------------------------ #
    async def create_bot(self, meeting_url: str, bot_name: str) -> dict[str, Any]:
        """Create a bot that records audio+video and (when possible) streams live captions.

        Live transcript chunks are delivered to our transcript webhook, which
        Recall must be able to reach over the public internet. Recall REJECTS
        localhost/private URLs with a 403 ``request_blocked``, so the real-time
        webhook is attached ONLY when ``MEETING_BOT_WEBHOOK_BASE_URL`` is a public
        https URL. Without it, the bot still records audio+video and captures
        participant names — only the live caption stream is skipped.
        """
        recording_config: dict[str, Any] = {
            "video_mixed_layout": "speaker_view",
            "video_mixed_mp4": {},          # mixed video recording
            "audio_mixed_mp3": {},          # mixed audio recording
            "participant_events": {},        # real participant names
            "meeting_metadata": {},
            "start_recording_on": "participant_join",
        }

        webhook_base = (settings.meeting_bot_webhook_base_url or "").strip().rstrip("/")
        if _is_public_url(webhook_base):
            recording_config["transcript"] = {"provider": {"meeting_captions": {}}}
            recording_config["realtime_endpoints"] = [
                {
                    "type": "webhook",
                    "url": f"{webhook_base}/api/meeting-bot/webhooks/recall/transcript",
                    "events": ["transcript.data", "transcript.partial_data"],
                }
            ]
            logger.info("Live captions enabled (webhook=%s).", webhook_base)
        else:
            logger.info(
                "Live captions disabled: MEETING_BOT_WEBHOOK_BASE_URL is not a public "
                "URL. Audio/video recording + participant names still work."
            )
        try:
            bot = await self._recall._request(
                "POST",
                "/bot",
                json={
                    "meeting_url": meeting_url,
                    "bot_name": bot_name,
                    "recording_config": recording_config,
                },
            )
        except RecallError:
            raise
        logger.info("Meeting-bot Recall bot created: id=%s", bot.get("id"))
        return bot

    async def get_bot(self, bot_id: str) -> dict[str, Any]:
        return await self._recall.get_bot(bot_id)

    async def delete_bot(self, bot_id: str) -> None:
        await self._recall.delete_bot(bot_id)

    async def leave_call(self, bot_id: str) -> None:
        """Make the bot leave the call gracefully so the recording finalizes.

        Preferred over deleting the bot (which can discard the recording). Falls
        back to delete if the leave endpoint isn't available.
        """
        try:
            await self._recall._request("POST", f"/bot/{bot_id}/leave_call")
        except Exception as exc:  # noqa: BLE001 — fall back to delete
            logger.warning("leave_call failed for bot %s (%s); deleting instead.", bot_id, exc)
            await self._recall.delete_bot(bot_id)

    async def get_speaker_timeline(self, bot_id: str) -> list[dict[str, Any]]:
        return await self._recall.get_speaker_timeline(bot_id)

    @staticmethod
    def verify_webhook(body: bytes, signature: str | None) -> bool:
        return RecallService.verify_webhook(body, signature)

    # ------------------------------------------------------------------ #
    # Recording URLs (audio + video, separately)
    # ------------------------------------------------------------------ #
    async def get_recording_urls(self, bot_id: str) -> dict[str, Optional[str]]:
        bot = await self.get_bot(bot_id)
        return {
            "video": self._shortcut_url(bot, ("video_mixed",)),
            "audio": self._shortcut_url(bot, ("audio_mixed",)),
        }

    @staticmethod
    def _shortcut_url(bot: dict[str, Any], names: tuple[str, ...]) -> Optional[str]:
        for rec in bot.get("recordings") or []:
            media = rec.get("media_shortcuts") or {}
            for name in names:
                data = (media.get(name) or {}).get("data") or {}
                if data.get("download_url"):
                    return data["download_url"]
        # Legacy fallbacks.
        return bot.get("video_url")

    # ------------------------------------------------------------------ #
    # Webhook parsing
    # ------------------------------------------------------------------ #
    @staticmethod
    def parse_status_event(payload: dict[str, Any]) -> dict[str, Any]:
        """Normalise a Recall status webhook into a flat dict."""
        data = payload.get("data", {}) or {}
        status = data.get("status")
        code = status.get("code") if isinstance(status, dict) else status
        bot_id = (
            data.get("bot_id")
            or (data.get("bot") or {}).get("id")
            or payload.get("bot_id")
        )
        return {
            "event": payload.get("event", ""),
            "status_code": code,
            "bot_id": bot_id,
            "event_id": payload.get("id")
            or f"{bot_id}:{payload.get('event','')}:{code}",
        }

    @staticmethod
    def parse_transcript_event(payload: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Normalise a Recall ``transcript.data`` webhook into one chunk.

        Recall's real-time transcript payload contains words with speaker info;
        we collapse them to a single utterance with start/end and speaker name.
        """
        data = payload.get("data", {}) or {}
        bot_id = (data.get("bot") or {}).get("id") or data.get("bot_id") or payload.get("bot_id")
        tr = data.get("data") or data.get("transcript") or data
        words = tr.get("words") or []
        participant = tr.get("participant") or {}
        speaker = participant.get("name") or tr.get("speaker") or None

        if words:
            text = " ".join(w.get("text", "") for w in words).strip()
            start = words[0].get("start_timestamp", {})
            end = words[-1].get("end_timestamp", {})
            start_t = start.get("relative") if isinstance(start, dict) else start
            end_t = end.get("relative") if isinstance(end, dict) else end
        else:
            text = (tr.get("text") or "").strip()
            start_t = tr.get("start_time") or tr.get("start")
            end_t = tr.get("end_time") or tr.get("end")

        if not text:
            return None
        event = payload.get("event", "")
        return {
            "bot_id": bot_id,
            "speaker_name": speaker,
            "start_time": float(start_t) if start_t is not None else None,
            "end_time": float(end_t) if end_t is not None else None,
            "text": text,
            "is_final": event != "transcript.partial_data",
        }
