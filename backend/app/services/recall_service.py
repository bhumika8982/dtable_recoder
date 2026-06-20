"""Recall.ai integration: dispatch recording bots and fetch recordings.

Recall.ai handles joining the meeting (Zoom/Meet/Teams) and recording it.
We only use it for join + recording, per project constraints. Transcription and
diarization are done locally with WhisperX / pyannote.

API reference: https://docs.recall.ai/
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class RecallError(RuntimeError):
    pass


class RecallService:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None,
    ):
        self.api_key = api_key or settings.recall_api_key
        self.base_url = (base_url or settings.recall_base_url).rstrip("/")
        self._client = client

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise RecallError("RECALL_API_KEY is not configured.")
        return {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": "application/json",
        }

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        client = self._client or httpx.AsyncClient(timeout=30.0)
        owns_client = self._client is None
        try:
            resp = await client.request(method, url, headers=self._headers(), **kwargs)
            if resp.status_code >= 400:
                raise RecallError(f"Recall API {resp.status_code}: {resp.text}")
            return resp.json() if resp.content else {}
        finally:
            if owns_client:
                await client.aclose()

    async def create_bot(
        self, meeting_url: str, bot_name: str = "Meeting Bot", join_at: str | None = None
    ) -> dict[str, Any]:
        """Create a bot that joins ``meeting_url`` and records the call.

        Returns the Recall bot object (contains ``id``).
        """
        payload: dict[str, Any] = {
            "meeting_url": meeting_url,
            "bot_name": bot_name,
            # Ask Recall to capture audio+video; we extract audio locally via ffmpeg.
            "recording_config": {"video_mixed_layout": "speaker_view"},
        }
        if join_at:
            payload["join_at"] = join_at
        logger.info("Creating Recall bot for meeting_url=%s (name=%r).", meeting_url, bot_name)
        bot = await self._request("POST", "/bot", json=payload)
        logger.info("Recall bot CREATED: id=%s.", bot.get("id"))
        return bot

    async def get_bot(self, bot_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/bot/{bot_id}")

    @staticmethod
    def extract_recording_url(bot: dict[str, Any]) -> Optional[str]:
        """Pull a downloadable recording URL out of an already-fetched bot dict.

        Prefers the mixed video; falls back to mixed audio, then the legacy
        ``video_url`` field used by some Recall responses. Returns ``None`` when
        the recording isn't ready yet.
        """
        recordings = bot.get("recordings") or []
        for rec in recordings:
            media = rec.get("media_shortcuts") or {}
            for shortcut in ("video_mixed", "audio_mixed"):
                data = (media.get(shortcut) or {}).get("data") or {}
                if data.get("download_url"):
                    return data["download_url"]
        return bot.get("video_url")

    async def get_recording_url(self, bot_id: str) -> Optional[str]:
        """Return a downloadable URL for the bot's recording, if ready."""
        bot = await self.get_bot(bot_id)
        url = self.extract_recording_url(bot)
        if url:
            logger.info("Recording URL received for bot %s.", bot_id)
        else:
            logger.info("Recording URL not available yet for bot %s.", bot_id)
        return url

    async def get_speaker_timeline(self, bot_id: str) -> list[dict[str, Any]]:
        """Return real per-speaker turns from Recall's participant events.

        Recall captures the meeting platform's active-speaker timeline together
        with the participants' real display names (e.g. "Bhumika Girhare"). We
        convert it to ``[{start, end, speaker}]`` (seconds, speaker = real name)
        so the transcript can show actual names instead of "Speaker 1".

        Returns an empty list when the data isn't available (e.g. the bot wasn't
        configured to capture participant events, or an audio-only meeting).
        """
        bot = await self.get_bot(bot_id)
        url = self._speaker_timeline_url(bot)
        if not url:
            logger.info("No Recall speaker_timeline available for bot %s.", bot_id)
            return []

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            timeline = resp.json()

        turns: list[dict[str, Any]] = []
        for entry in timeline or []:
            name = ((entry.get("participant") or {}).get("name") or "").strip()
            start = (entry.get("start_timestamp") or {}).get("relative")
            end_ts = entry.get("end_timestamp") or {}
            end = end_ts.get("relative") if end_ts else None
            if name and start is not None:
                turns.append(
                    {
                        "start": float(start),
                        # An open turn (still speaking at recording end) covers the
                        # rest of the audio.
                        "end": float(end) if end is not None else float("inf"),
                        "speaker": name,
                    }
                )
        turns.sort(key=lambda t: t["start"])
        logger.info(
            "Recall speaker_timeline for bot %s: %d turns, speakers=%s.",
            bot_id,
            len(turns),
            sorted({t["speaker"] for t in turns}),
        )
        return turns

    @staticmethod
    def _speaker_timeline_url(bot: dict[str, Any]) -> Optional[str]:
        for rec in bot.get("recordings") or []:
            data = (
                ((rec.get("media_shortcuts") or {}).get("participant_events") or {}).get(
                    "data"
                )
                or {}
            )
            if data.get("speaker_timeline_download_url"):
                return data["speaker_timeline_download_url"]
        return None

    async def delete_bot(self, bot_id: str) -> None:
        await self._request("DELETE", f"/bot/{bot_id}")

    @staticmethod
    def verify_webhook(body: bytes, signature: str | None) -> bool:
        """Validate the webhook HMAC signature when a secret is configured.

        If no secret is set, validation is skipped (returns True) so local
        development without signing still works.
        """
        secret = settings.recall_webhook_secret
        if not secret:
            return True
        if not signature:
            return False
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        # Signatures may be sent as "sha256=<hex>"; normalise.
        provided = signature.split("=", 1)[-1].strip()
        return hmac.compare_digest(expected, provided)
