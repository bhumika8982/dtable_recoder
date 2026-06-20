"""Merge WhisperX transcript segments with pyannote speaker turns.

Strategy: for each transcript segment, assign the speaker whose diarization
turns have the greatest temporal overlap with the segment. Word-level timings
(when available from WhisperX alignment) make this assignment more precise.
"""
from __future__ import annotations

import re
from typing import Any


def format_timestamp(seconds: float) -> str:
    """Seconds -> ``HH:MM:SS`` for display, e.g. 72.4 -> ``00:01:12``."""
    s = max(0, int(round(seconds)))
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def friendly_speaker(label: str | None) -> str:
    """Map a raw diarization label to a readable name: ``SPEAKER_00`` -> ``Speaker 1``."""
    if not label or label == "UNKNOWN":
        return "Unknown"
    m = re.search(r"(\d+)\s*$", label)
    if m:
        return f"Speaker {int(m.group(1)) + 1}"
    return label


def _overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def _speaker_for_interval(
    start: float, end: float, turns: list[dict[str, Any]], default_speaker: str = "UNKNOWN"
) -> str:
    best_speaker = default_speaker
    best_overlap = 0.0
    for turn in turns:
        ov = _overlap(start, end, turn["start"], turn["end"])
        if ov > best_overlap:
            best_overlap = ov
            best_speaker = turn["speaker"]
    return best_speaker


def merge_transcript_with_speakers(
    transcript: dict[str, Any], speaker_turns: list[dict[str, Any]]
) -> dict[str, Any]:
    """Return a merged transcript with a ``speaker`` on each segment.

    ``transcript`` is the WhisperX output ``{language, segments:[{start,end,text,words}]}``.
    ``speaker_turns`` is the pyannote output ``[{start,end,speaker}]``.
    """
    merged_segments: list[dict[str, Any]] = []

    # When diarization is unavailable, attribute everything to a single speaker
    # ("Speaker 1") instead of "Unknown" so the transcript still reads cleanly.
    default_speaker = "UNKNOWN" if speaker_turns else "SPEAKER_00"

    for seg in transcript.get("segments", []):
        words = seg.get("words") or []
        if words:
            # Vote per word for finer accuracy, then take the majority speaker.
            votes: dict[str, float] = {}
            for w in words:
                w_start = float(w.get("start", seg["start"]))
                w_end = float(w.get("end", w_start))
                spk = _speaker_for_interval(w_start, w_end, speaker_turns, default_speaker)
                votes[spk] = votes.get(spk, 0.0) + (w_end - w_start)
            speaker = max(votes, key=votes.get) if votes else default_speaker
        else:
            speaker = _speaker_for_interval(
                seg["start"], seg["end"], speaker_turns, default_speaker
            )

        merged_segments.append(
            {
                "start": float(seg["start"]),
                "end": float(seg["end"]),
                "speaker": speaker,
                "speaker_label": friendly_speaker(speaker),
                "text": (seg.get("text") or "").strip(),
            }
        )

    # Coalescing groups consecutive same-speaker segments. Without diarization
    # every segment is "Speaker 1", which would collapse the whole transcript
    # into one block — so only coalesce when we actually have speaker turns.
    if speaker_turns:
        merged_segments = _coalesce_adjacent(merged_segments)
    formatted = _format_full_text(merged_segments)
    return {
        "language": transcript.get("language"),
        "segments": merged_segments,
        # Readable, saved transcript: "[HH:MM:SS] Speaker N: text" per line.
        "full_text": formatted,
        "formatted": formatted,
    }


def _coalesce_adjacent(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge consecutive segments from the same speaker into one block."""
    if not segments:
        return []
    out = [dict(segments[0])]
    for seg in segments[1:]:
        last = out[-1]
        if seg["speaker"] == last["speaker"]:
            last["end"] = seg["end"]
            last["text"] = (last["text"] + " " + seg["text"]).strip()
        else:
            out.append(dict(seg))
    return out


def _format_full_text(segments: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"[{format_timestamp(s['start'])}] {friendly_speaker(s['speaker'])}: {s['text']}"
        for s in segments
        if s["text"]
    )
