"""Deepgram Nova-3 transcription via REST API.

Uses httpx directly (already installed) to avoid deepgram-sdk version issues.
Nova-3 is Deepgram's highest-accuracy model for Hindi, English, and Hinglish.

Priority order in pipeline:
  1. Deepgram   (DEEPGRAM_API_KEY set)   ← this file
  2. AssemblyAI (ASSEMBLYAI_API_KEY set)
  3. WhisperX   (local fallback)
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"


class DeepgramService:
    def __init__(self, api_key: str, language: str = "hi"):
        self._api_key = api_key
        # "hi"    = Hindi + Hinglish (English words in Hindi speech handled well)
        # "en"    = English only
        # "multi" = Auto-detect multilingual
        self._language = language or "hi"

    async def transcribe(
        self,
        audio_path: str,
        num_speakers: Optional[int] = None,
    ) -> dict[str, Any]:
        """Transcribe audio and return segments with speaker labels.

        Returns::

            {
                "segments": [
                    {"text": "...", "speaker_label": "Speaker 0",
                     "start": 1.23, "end": 4.56, "confidence": 0.97},
                    ...
                ],
                "full_text": "[00:00:01] Speaker 0: ...",
                "language": "hi",
                "confidence": 0.95,
            }
        """
        ext = os.path.splitext(audio_path)[1].lower()
        mime = {
            ".mp3": "audio/mpeg",
            ".mp4": "video/mp4",
            ".wav": "audio/wav",
            ".m4a": "audio/mp4",
            ".ogg": "audio/ogg",
            ".webm": "audio/webm",
        }.get(ext, "audio/mpeg")

        logger.info(
            "Deepgram: submitting  path=%s  lang=%s  speakers=%s  model=nova-3",
            audio_path, self._language, num_speakers,
        )

        with open(audio_path, "rb") as f:
            audio_data = f.read()

        params: dict[str, Any] = {
            "model":        "nova-3",
            "language":     self._language,
            "diarize":      "true",
            "utterances":   "true",
            "punctuate":    "true",
            "smart_format": "true",
            "filler_words": "false",
        }
        if num_speakers:
            params["diarize"] = "true"

        headers = {
            "Authorization": f"Token {self._api_key}",
            "Content-Type":  mime,
        }

        async with httpx.AsyncClient(timeout=600) as client:
            response = await client.post(
                DEEPGRAM_URL,
                params=params,
                headers=headers,
                content=audio_data,
            )

        if response.status_code != 200:
            raise RuntimeError(
                f"Deepgram API error {response.status_code}: {response.text[:300]}"
            )

        data = response.json()
        return self._parse(data)

    def _parse(self, data: dict) -> dict[str, Any]:
        results    = data.get("results") or {}
        utterances = results.get("utterances") or []
        channels   = results.get("channels") or [{}]

        detected_lang = channels[0].get("detected_language") or self._language
        alts          = channels[0].get("alternatives") or [{}]
        overall_conf  = alts[0].get("confidence") or 0.0

        logger.info(
            "Deepgram: done — %d utterances  lang=%s  confidence=%.0f%%",
            len(utterances), detected_lang, overall_conf * 100,
        )

        segments: list[dict[str, Any]] = []
        for utt in utterances:
            text = (utt.get("transcript") or "").strip()
            if not text:
                continue
            segments.append({
                "text":         text,
                "speaker_label": f"Speaker {utt.get('speaker', 0)}",
                "start":        float(utt.get("start") or 0),
                "end":          float(utt.get("end")   or 0),
                "confidence":   float(utt.get("confidence") or 0),
            })

        lines = []
        for seg in segments:
            s  = int(seg["start"])
            ts = f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"
            lines.append(f"[{ts}] {seg['speaker_label']}: {seg['text']}")

        return {
            "segments":   segments,
            "full_text":  "\n".join(lines),
            "language":   detected_lang,
            "confidence": overall_conf,
        }
