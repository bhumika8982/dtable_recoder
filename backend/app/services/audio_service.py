"""FFmpeg-based audio extraction.

Extracts a mono 16 kHz WAV from the recorded video, which is the format WhisperX
and pyannote expect. Runs ffmpeg in a subprocess off the event loop.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
from functools import partial

from app.config import settings


class AudioExtractionError(RuntimeError):
    pass


def _run_ffmpeg(video_path: str, audio_path: str, sample_rate: int) -> str:
    cmd = [
        settings.ffmpeg_bin,
        "-y",                      # overwrite output
        "-i", video_path,
        "-vn",                     # drop video
        "-ac", "1",                # mono
        "-ar", str(sample_rate),   # 16 kHz
        "-acodec", "pcm_s16le",    # 16-bit PCM
        audio_path,
    ]
    # NOTE: use the blocking subprocess API (run in a thread executor by the
    # async wrapper). asyncio.create_subprocess_exec raises NotImplementedError
    # on Windows under uvicorn's event loop, which broke audio extraction here.
    proc = subprocess.run(cmd, capture_output=True)

    if proc.returncode != 0:
        raise AudioExtractionError(
            f"ffmpeg failed (code {proc.returncode}): {proc.stderr.decode(errors='ignore')[-2000:]}"
        )
    if not os.path.exists(audio_path):
        raise AudioExtractionError("ffmpeg reported success but output file is missing.")
    return audio_path


async def extract_audio(video_path: str, audio_path: str, sample_rate: int = 16000) -> str:
    """Extract mono PCM WAV audio from ``video_path`` into ``audio_path``.

    Returns the output path on success.
    """
    if not os.path.exists(video_path):
        raise AudioExtractionError(f"Input video not found: {video_path}")

    os.makedirs(os.path.dirname(os.path.abspath(audio_path)), exist_ok=True)

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, partial(_run_ffmpeg, video_path, audio_path, sample_rate)
    )
