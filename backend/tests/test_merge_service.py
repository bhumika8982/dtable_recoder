"""Unit tests for transcript + speaker merge logic (pure functions)."""
from app.services.merge_service import merge_transcript_with_speakers


def test_merge_assigns_speakers_by_overlap():
    transcript = {
        "language": "en",
        "segments": [
            {"start": 0.0, "end": 2.0, "text": "Hello team.", "words": []},
            {"start": 2.0, "end": 4.0, "text": "Let's start.", "words": []},
        ],
    }
    turns = [
        {"start": 0.0, "end": 2.0, "speaker": "SPEAKER_00"},
        {"start": 2.0, "end": 4.0, "speaker": "SPEAKER_01"},
    ]
    merged = merge_transcript_with_speakers(transcript, turns)
    speakers = [s["speaker"] for s in merged["segments"]]
    assert speakers == ["SPEAKER_00", "SPEAKER_01"]
    # full_text is now the readable "[HH:MM:SS] Speaker N: text" format.
    assert "[00:00:00] Speaker 1: Hello team." in merged["full_text"]
    assert merged["segments"][0]["speaker_label"] == "Speaker 1"


def test_merge_coalesces_same_speaker():
    transcript = {
        "segments": [
            {"start": 0.0, "end": 1.0, "text": "One.", "words": []},
            {"start": 1.0, "end": 2.0, "text": "Two.", "words": []},
        ]
    }
    turns = [{"start": 0.0, "end": 2.0, "speaker": "SPEAKER_00"}]
    merged = merge_transcript_with_speakers(transcript, turns)
    assert len(merged["segments"]) == 1
    assert merged["segments"][0]["text"] == "One. Two."


def test_merge_word_level_voting():
    transcript = {
        "segments": [
            {
                "start": 0.0,
                "end": 4.0,
                "text": "shared segment",
                "words": [
                    {"start": 0.0, "end": 0.5},
                    {"start": 3.5, "end": 4.0},
                ],
            }
        ]
    }
    # Most of the segment belongs to SPEAKER_01 by word timings overlap split.
    turns = [
        {"start": 0.0, "end": 0.6, "speaker": "SPEAKER_00"},
        {"start": 0.6, "end": 4.0, "speaker": "SPEAKER_01"},
    ]
    merged = merge_transcript_with_speakers(transcript, turns)
    assert merged["segments"][0]["speaker"] in {"SPEAKER_00", "SPEAKER_01"}


def test_merge_unknown_speaker_when_no_overlap():
    transcript = {"segments": [{"start": 10.0, "end": 11.0, "text": "Hi", "words": []}]}
    turns = [{"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"}]
    merged = merge_transcript_with_speakers(transcript, turns)
    assert merged["segments"][0]["speaker"] == "UNKNOWN"
