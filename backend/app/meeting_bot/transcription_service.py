"""High-accuracy transcription for the optional audio/video re-runs.

Reuses the existing WhisperX transcription, pyannote diarization and the merge
logic, then converts the result into source-tagged transcript *chunks* (one per
utterance) ready to persist. Long media is handled naturally by WhisperX's own
segmenting; chunk text is additionally available for embeddings.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from app.meeting_bot.models import Source
from app.services.diarization_service import get_diarization_service
from app.services.merge_service import merge_transcript_with_speakers
from app.services.transcription_service import get_transcription_service

logger = logging.getLogger(__name__)


async def transcribe_to_chunks(
    audio_path: str,
    meeting_id: str,
    bot_id: Optional[str],
    source: Source,
    num_speakers: Optional[int] = None,
    speaker_turns: Optional[list[dict[str, Any]]] = None,
) -> tuple[list[dict[str, Any]], str, str]:
    """Transcribe ``audio_path`` and return ``(chunks, full_text, language)``.

    ``speaker_turns`` lets the caller supply real names (e.g. Recall timeline);
    otherwise pyannote diarization is used (best-effort, never fatal).
    ``language`` is the ISO 639-1 code auto-detected by WhisperX (e.g. "hi",
    "en") — empty string when detection was inconclusive.
    """
    logger.info("[%s] Transcription started: %s", source.value, audio_path)
    raw = await get_transcription_service().transcribe(audio_path)
    detected_language = raw.get("language") or ""
    logger.info(
        "[%s] Transcription done: %d segments (lang=%s)",
        source.value, len(raw.get("segments", [])), detected_language,
    )

    if speaker_turns is None:
        try:
            speaker_turns = await get_diarization_service().diarize(
                audio_path, num_speakers=num_speakers
            )
            logger.info("[%s] Diarization done: %d turns", source.value, len(speaker_turns))
        except Exception as exc:  # noqa: BLE001 — diarization is best-effort
            logger.warning("[%s] Diarization skipped: %s", source.value, exc)
            speaker_turns = []

    merged = merge_transcript_with_speakers(raw, speaker_turns or [])
    chunks = segments_to_chunks(merged["segments"], meeting_id, bot_id, source)
    return chunks, merged.get("full_text", ""), detected_language


def segments_to_chunks(
    segments: list[dict[str, Any]],
    meeting_id: str,
    bot_id: Optional[str],
    source: Source,
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for i, seg in enumerate(segments):
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        chunks.append(
            {
                "chunk_id": uuid.uuid4().hex,
                "meeting_id": meeting_id,
                "bot_id": bot_id,
                "source": source.value,
                "speaker_name": seg.get("speaker_label") or seg.get("speaker"),
                "start_time": float(seg.get("start", 0.0)),
                "end_time": float(seg.get("end", 0.0)),
                "text": text,
                "is_final": True,
                "chunk_index": i,
                "embedding_id": None,
            }
        )
    return chunks
