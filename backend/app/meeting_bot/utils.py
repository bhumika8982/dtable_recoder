"""Small helpers for the meeting-bot flow: correlation IDs, time, chunking."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any


def now() -> datetime:
    return datetime.now(timezone.utc)


def new_correlation_id() -> str:
    """Short id used to trace one meeting operation across logs."""
    return uuid.uuid4().hex[:12]


def fmt_timestamp(seconds: float) -> str:
    """Seconds -> ``HH:MM:SS`` (e.g. 72.4 -> ``00:01:12``)."""
    s = max(0, int(round(seconds or 0)))
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def friendly_speaker(label: str | None) -> str:
    """Map a raw diarization label to a readable name; pass real names through."""
    if not label or label == "UNKNOWN":
        return "Unknown"
    s = str(label)
    # Raw pyannote labels look like SPEAKER_00 -> "Speaker 1".
    if s.upper().startswith("SPEAKER_"):
        try:
            return f"Speaker {int(s.split('_')[-1]) + 1}"
        except ValueError:
            return s
    return s  # already a real name (e.g. from Recall participant data)


def chunk_text_by_chars(text: str, max_chars: int = 4000, overlap: int = 200) -> list[str]:
    """Split a long transcript into overlapping character windows.

    Used for embeddings and for map-reduce style LLM calls on long transcripts.
    """
    text = text or ""
    if len(text) <= max_chars:
        return [text] if text.strip() else []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap
    return chunks


def segments_to_text(segments: list[dict[str, Any]]) -> str:
    """Render merged segments as ``[HH:MM:SS] Speaker: text`` lines."""
    lines = []
    for s in segments:
        spk = s.get("speaker_label") or friendly_speaker(s.get("speaker"))
        txt = (s.get("text") or "").strip()
        if txt:
            lines.append(f"[{fmt_timestamp(s.get('start', 0))}] {spk}: {txt}")
    return "\n".join(lines)
