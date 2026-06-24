"""WhisperX transcription service.

Loads a WhisperX model lazily (it's expensive) and caches it for reuse. Device
and compute type auto-detect: CUDA + float16 when a GPU is present, otherwise
CPU + int8. Heavy work runs in a thread executor to keep the event loop free.
"""
from __future__ import annotations

import asyncio
from functools import partial
from typing import Any, Optional

from app.config import settings


def _resolve_device() -> str:
    if settings.whisper_device != "auto":
        return settings.whisper_device
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _resolve_compute_type(device: str) -> str:
    if settings.whisper_compute_type and settings.whisper_compute_type != "auto":
        return settings.whisper_compute_type
    return "float16" if device == "cuda" else "int8"


class TranscriptionService:
    """Wraps WhisperX. Models are loaded once and cached on the instance."""

    def __init__(self) -> None:
        self.device = _resolve_device()
        self.compute_type = _resolve_compute_type(self.device)
        self._model = None
        self._align_model = None
        self._align_metadata = None
        self._align_lang: Optional[str] = None

    def _load_model(self):
        if self._model is None:
            # Compat shims for newer torch / huggingface_hub used by WhisperX's
            # pyannote-based VAD checkpoint.
            from app.hf_compat import patch_hf_hub_download
            from app.speechbrain_compat import patch_speechbrain_k2
            from app.torch_compat import patch_torch_load
            from app.whisperx_compat import patch_whisperx_ffmpeg

            patch_torch_load()  # WhisperX VAD checkpoint needs weights_only=False
            patch_hf_hub_download()  # use_auth_token -> token
            patch_speechbrain_k2()  # stub k2 before whisperx pulls in speechbrain
            patch_whisperx_ffmpeg()  # use settings.ffmpeg_bin instead of bare "ffmpeg"
            import whisperx

            self._model = whisperx.load_model(
                settings.whisper_model,
                self.device,
                compute_type=self.compute_type,
                language=settings.whisper_language,
            )
        return self._model

    def _transcribe_sync(self, audio_path: str) -> dict[str, Any]:
        import whisperx

        model = self._load_model()
        audio = whisperx.load_audio(audio_path)
        # Pass language=None so WhisperX auto-detects per file (prevents the
        # model from locking onto its init language for multilingual meetings).
        # task="transcribe" ensures speech is kept in the original language —
        # never silently translated into English.
        result = model.transcribe(
            audio,
            batch_size=settings.whisper_batch_size,
            language=settings.whisper_language,  # None → auto-detect
            task="transcribe",
        )

        language = result.get("language", settings.whisper_language or "en")

        # No speech detected (silence / music only): WhisperX's aligner indexes
        # into the first segment and raises IndexError on an empty list, so skip
        # alignment and return an empty transcript. The pipeline treats an empty
        # transcript as "completed, no MOM" rather than a failure.
        if not result.get("segments"):
            return {"language": language, "segments": []}

        # Fast path: word-level alignment is expensive on CPU and only sharpens
        # per-word speaker assignment (useful with diarization). When disabled,
        # return segment-level results directly — much faster.
        if not settings.whisper_align:
            segments = [
                {
                    "start": float(seg.get("start", 0.0)),
                    "end": float(seg.get("end", 0.0)),
                    "text": (seg.get("text") or "").strip(),
                    "words": [],
                }
                for seg in result.get("segments", [])
            ]
            return {"language": language, "segments": segments}

        # Word-level alignment improves the speaker merge later.
        if self._align_model is None or self._align_lang != language:
            self._align_model, self._align_metadata = whisperx.load_align_model(
                language_code=language, device=self.device
            )
            self._align_lang = language

        aligned = whisperx.align(
            result["segments"],
            self._align_model,
            self._align_metadata,
            audio,
            self.device,
            return_char_alignments=False,
        )

        segments = [
            {
                "start": float(seg.get("start", 0.0)),
                "end": float(seg.get("end", 0.0)),
                "text": (seg.get("text") or "").strip(),
                "words": seg.get("words", []),
            }
            for seg in aligned.get("segments", [])
        ]
        return {"language": language, "segments": segments}

    async def transcribe(self, audio_path: str) -> dict[str, Any]:
        """Transcribe ``audio_path`` and return ``{language, segments}``."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, partial(self._transcribe_sync, audio_path))


# Module-level singleton so models stay warm across requests.
_service: Optional[TranscriptionService] = None


def get_transcription_service() -> TranscriptionService:
    global _service
    if _service is None:
        _service = TranscriptionService()
    return _service
