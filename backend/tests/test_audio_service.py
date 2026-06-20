"""Tests for ffmpeg audio extraction.

We avoid requiring a real ffmpeg binary by stubbing the subprocess call, and
verify the constructed command and error handling.
"""
import os

import pytest

import app.services.audio_service as audio_service
from app.services.audio_service import AudioExtractionError, extract_audio


class FakeCompleted:
    """Mimics subprocess.CompletedProcess."""

    def __init__(self, returncode=0, stderr=b""):
        self.returncode = returncode
        self.stderr = stderr


@pytest.mark.asyncio
async def test_extract_audio_builds_command(tmp_path, monkeypatch):
    video = tmp_path / "in.mp4"
    video.write_bytes(b"fake")
    out = tmp_path / "out.wav"

    captured = {}

    def fake_run(cmd, capture_output=False, **kwargs):
        captured["cmd"] = cmd
        out.write_bytes(b"RIFF")  # simulate ffmpeg writing output
        return FakeCompleted(returncode=0)

    monkeypatch.setattr(audio_service.subprocess, "run", fake_run)

    result = await extract_audio(str(video), str(out))
    assert os.path.exists(result)
    assert "-ac" in captured["cmd"] and "1" in captured["cmd"]
    assert "16000" in captured["cmd"]


@pytest.mark.asyncio
async def test_extract_audio_missing_input():
    with pytest.raises(AudioExtractionError):
        await extract_audio("/no/such/file.mp4", "/tmp/out.wav")


@pytest.mark.asyncio
async def test_extract_audio_ffmpeg_failure(tmp_path, monkeypatch):
    video = tmp_path / "in.mp4"
    video.write_bytes(b"fake")

    def fake_run(cmd, capture_output=False, **kwargs):
        return FakeCompleted(returncode=1, stderr=b"boom")

    monkeypatch.setattr(audio_service.subprocess, "run", fake_run)

    with pytest.raises(AudioExtractionError):
        await extract_audio(str(video), str(tmp_path / "out.wav"))
