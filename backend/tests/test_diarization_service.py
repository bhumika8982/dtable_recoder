"""Tests for pyannote diarization wiring using a fake pipeline."""
import pytest

from app.services.diarization_service import DiarizationService


class FakeSegment:
    def __init__(self, start, end):
        self.start = start
        self.end = end


class FakeDiarization:
    def __init__(self, tracks):
        self._tracks = tracks

    def itertracks(self, yield_label=True):
        for start, end, spk in self._tracks:
            yield FakeSegment(start, end), None, spk


@pytest.mark.asyncio
async def test_diarize_returns_sorted_turns(monkeypatch):
    svc = DiarizationService()

    fake_pipeline = lambda audio_path, **kw: FakeDiarization(
        [(2.0, 4.0, "SPEAKER_01"), (0.0, 2.0, "SPEAKER_00")]
    )
    monkeypatch.setattr(svc, "_load_pipeline", lambda: fake_pipeline)

    turns = await svc.diarize("/tmp/audio.wav")
    assert [t["start"] for t in turns] == [0.0, 2.0]
    assert turns[0]["speaker"] == "SPEAKER_00"
    assert turns[1]["speaker"] == "SPEAKER_01"
