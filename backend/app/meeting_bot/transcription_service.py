"""High-accuracy transcription for the optional audio/video re-runs.

Uses AssemblyAI (cloud) when ASSEMBLYAI_API_KEY is set in .env — it handles
English, Hindi, and Hinglish mixing automatically and returns speaker-labelled
segments without needing WhisperX or pyannote locally.

Falls back to the local WhisperX + pyannote pipeline when no AssemblyAI key
is configured.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from app.meeting_bot.models import Source

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

    Prefers AssemblyAI (cloud) when ASSEMBLYAI_API_KEY is set.
    Falls back to local WhisperX + pyannote otherwise.
    """
    from app.config import settings

    # Priority: Deepgram → AssemblyAI → WhisperX (local)
    if settings.deepgram_api_key:
        return await _transcribe_deepgram(
            audio_path, meeting_id, bot_id, source, num_speakers
        )
    if settings.assemblyai_api_key:
        return await _transcribe_assemblyai(
            audio_path, meeting_id, bot_id, source, num_speakers
        )
    return await _transcribe_whisperx(
        audio_path, meeting_id, bot_id, source, num_speakers, speaker_turns
    )


# --------------------------------------------------------------------------- #
# Deepgram path  (Nova-3, highest accuracy)
# --------------------------------------------------------------------------- #
async def _transcribe_deepgram(
    audio_path: str,
    meeting_id: str,
    bot_id: Optional[str],
    source: Source,
    num_speakers: Optional[int],
) -> tuple[list[dict[str, Any]], str, str]:
    from app.config import settings
    from app.services.deepgram_service import DeepgramService

    logger.info("[%s] Using Deepgram Nova-3 transcription: %s", source.value, audio_path)
    svc = DeepgramService(settings.deepgram_api_key, language=settings.deepgram_language)
    result = await svc.transcribe(audio_path, num_speakers=num_speakers)

    detected_language = result.get("language", "")
    segments = result.get("segments", [])
    confidence = result.get("confidence", 0)
    logger.info(
        "[%s] Deepgram done: %d segments  lang=%s  confidence=%.0f%%",
        source.value, len(segments), detected_language, confidence * 100,
    )

    chunks = segments_to_chunks(segments, meeting_id, bot_id, source)
    return chunks, result.get("full_text", ""), detected_language


# --------------------------------------------------------------------------- #
# AssemblyAI path
# --------------------------------------------------------------------------- #
async def _transcribe_assemblyai(
    audio_path: str,
    meeting_id: str,
    bot_id: Optional[str],
    source: Source,
    num_speakers: Optional[int],
) -> tuple[list[dict[str, Any]], str, str]:
    from app.config import settings
    from app.services.assemblyai_service import AssemblyAIService

    logger.info("[%s] Using AssemblyAI transcription: %s", source.value, audio_path)
    svc = AssemblyAIService(settings.assemblyai_api_key, language=settings.assemblyai_language)
    result = await svc.transcribe(audio_path, num_speakers=num_speakers)

    detected_language = result.get("language", "")
    segments = result.get("segments", [])
    logger.info(
        "[%s] AssemblyAI done: %d segments (lang=%s)",
        source.value, len(segments), detected_language,
    )

    chunks = segments_to_chunks(segments, meeting_id, bot_id, source)
    return chunks, result.get("full_text", ""), detected_language


# --------------------------------------------------------------------------- #
# WhisperX + pyannote fallback path
# --------------------------------------------------------------------------- #
async def _transcribe_whisperx(
    audio_path: str,
    meeting_id: str,
    bot_id: Optional[str],
    source: Source,
    num_speakers: Optional[int],
    speaker_turns: Optional[list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], str, str]:
    from app.services.diarization_service import get_diarization_service
    from app.services.merge_service import merge_transcript_with_speakers
    from app.services.transcription_service import get_transcription_service

    logger.info("[%s] Using WhisperX transcription: %s", source.value, audio_path)
    raw = await get_transcription_service().transcribe(audio_path)
    detected_language = raw.get("language") or ""
    logger.info(
        "[%s] WhisperX done: %d segments (lang=%s)",
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
