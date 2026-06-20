"""Tests for WhisperX transcription wiring.

WhisperX (and torch) are heavy/optional in CI, so we inject a fake ``whisperx``
module and assert the service normalises WhisperX output into our schema.
"""
import sys
import types

import pytest

from app.services.transcription_service import (
    TranscriptionService,
    _resolve_compute_type,
)


def _install_fake_whisperx(monkeypatch):
    fake = types.ModuleType("whisperx")

    class FakeModel:
        def transcribe(self, audio, batch_size):
            return {
                "language": "en",
                "segments": [{"start": 0.0, "end": 1.0, "text": "Hello"}],
            }

    fake.load_model = lambda *a, **k: FakeModel()
    fake.load_audio = lambda path: "AUDIO_ARRAY"
    fake.load_align_model = lambda language_code, device: ("ALIGN", {"meta": True})

    def fake_align(segments, model, meta, audio, device, return_char_alignments):
        # echo segments back with empty word lists
        return {"segments": [{**s, "words": []} for s in segments]}

    fake.align = fake_align
    monkeypatch.setitem(sys.modules, "whisperx", fake)


def test_resolve_compute_type_cpu_defaults_int8(monkeypatch):
    from app.services import transcription_service as ts

    monkeypatch.setattr(ts.settings, "whisper_compute_type", "auto")
    assert _resolve_compute_type("cpu") == "int8"
    assert _resolve_compute_type("cuda") == "float16"


@pytest.mark.asyncio
async def test_transcribe_normalises_output(monkeypatch):
    _install_fake_whisperx(monkeypatch)
    svc = TranscriptionService()
    svc.device = "cpu"
    result = await svc.transcribe("/tmp/audio.wav")

    assert result["language"] == "en"
    assert result["segments"][0]["text"] == "Hello"
    assert "words" in result["segments"][0]
