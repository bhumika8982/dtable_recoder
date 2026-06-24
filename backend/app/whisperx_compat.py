"""Compatibility shim: make whisperx.load_audio use the configured ffmpeg binary.

WhisperX hardcodes "ffmpeg" as a bare command in whisperx/audio.py, so it fails
on Windows when ffmpeg is not on PATH (e.g. installed via winget to a long path
and the server process inherited an old PATH). This patch replaces the first
element of whisperx's internal ffmpeg command with settings.ffmpeg_bin so the
same binary used by our audio_service is also used by whisperx.
"""
from __future__ import annotations

import logging
import subprocess
from functools import wraps
from typing import Optional

logger = logging.getLogger(__name__)

_patched = False


def patch_whisperx_ffmpeg() -> None:
    """Idempotently patch whisperx.audio.load_audio to use settings.ffmpeg_bin."""
    global _patched
    if _patched:
        return

    from app.config import settings
    import whisperx.audio as _wx_audio

    ffmpeg_bin = settings.ffmpeg_bin
    _orig_load_audio = _wx_audio.load_audio

    @wraps(_orig_load_audio)
    def _patched_load_audio(file: str, sr: int = _wx_audio.SAMPLE_RATE):
        cmd = [
            ffmpeg_bin,
            "-nostdin",
            "-threads", "0",
            "-i", file,
            "-f", "s16le",
            "-ac", "1",
            "-acodec", "pcm_s16le",
            "-ar", str(sr),
            "-",
        ]
        try:
            out = subprocess.run(cmd, capture_output=True, check=True).stdout
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to load audio: {e.stderr.decode()}") from e
        import numpy as np
        return np.frombuffer(out, np.int16).flatten().astype(np.float32) / 32768.0

    _wx_audio.load_audio = _patched_load_audio
    # whisperx.audio is also re-exported at the package level
    try:
        import whisperx as _wx
        _wx.load_audio = _patched_load_audio
    except Exception:
        pass

    _patched = True
    logger.info("Patched whisperx.load_audio to use ffmpeg_bin: %s", ffmpeg_bin)
