"""Video handling: extract audio from a recorded video for transcription."""
from __future__ import annotations

import logging
import os

from app.meeting_bot.audio_service import ensure_wav, work_dir

logger = logging.getLogger(__name__)


async def video_to_wav(video_path: str, meeting_id: str) -> str:
    """Extract a transcription-ready WAV from a video file."""
    out = os.path.join(work_dir(meeting_id), "video_audio.wav")
    logger.info("Extracting audio from video for meeting %s", meeting_id)
    return await ensure_wav(video_path, out)
