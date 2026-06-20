"""Audio handling for the meeting-bot flow (download + ensure-WAV)."""
from __future__ import annotations

import logging
import os

import httpx

from app.config import settings
from app.services.audio_service import extract_audio

logger = logging.getLogger(__name__)


def work_dir(meeting_id: str) -> str:
    base = os.path.join(settings.work_dir, "mb", meeting_id)
    os.makedirs(base, exist_ok=True)
    return base


async def download(url: str, dest: str) -> str:
    """Stream a (possibly large) file to ``dest`` with a couple of retries."""
    last: Exception | None = None
    for attempt in range(1, 4):
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("GET", url) as resp:
                    resp.raise_for_status()
                    with open(dest, "wb") as f:
                        async for chunk in resp.aiter_bytes(1 << 20):
                            f.write(chunk)
            return dest
        except Exception as exc:  # noqa: BLE001 — retry transient network drops
            last = exc
            logger.warning("Download attempt %d failed (%s); retrying...", attempt, exc)
    raise RuntimeError(f"Download failed after retries: {last}")


async def ensure_wav(media_path: str, out_path: str) -> str:
    """Extract a 16 kHz mono WAV from any audio/video file (ffmpeg)."""
    return await extract_audio(media_path, out_path)
