"""pyannote.audio speaker diarization service.

Loads the diarization pipeline lazily (requires a HuggingFace token to download
the gated model). Returns speaker turns as ``[{start, end, speaker}]``.
"""
from __future__ import annotations

import asyncio
import logging
from functools import partial
from typing import Any, Optional

from app.config import settings

logger = logging.getLogger(__name__)

# Shown when no HuggingFace token is configured in .env.
_MISSING_TOKEN_MSG = (
    "Hugging Face token missing. Please set HUGGINGFACE_TOKEN in .env"
)


class DiarizationError(RuntimeError):
    pass


class DiarizationService:
    def __init__(self) -> None:
        self._pipeline = None
        self.device = _resolve_device()

    def _load_pipeline(self):
        if self._pipeline is None:
            if not settings.hf_token:
                logger.error("Hugging Face token MISSING — cannot load diarization model.")
                raise DiarizationError(_MISSING_TOKEN_MSG)
            logger.info("Hugging Face token loaded; preparing pyannote diarization model.")

            # Compat shims: torch 2.6+ weights_only, huggingface_hub's removal of
            # the deprecated use_auth_token argument that pyannote still passes,
            # and speechbrain's optional k2 integration (un-installable on Windows)
            # that otherwise crashes embedding-model loading.
            from app.hf_compat import patch_hf_hub_download
            from app.speechbrain_compat import patch_speechbrain_k2
            from app.torch_compat import patch_torch_load

            patch_torch_load()
            patch_hf_hub_download()
            patch_speechbrain_k2()

            import torch
            from pyannote.audio import Pipeline

            logger.info("Diarization model loading STARTED (%s).", settings.diarization_model)
            try:
                # NOTE: `use_auth_token` is pyannote's own public parameter name;
                # the hf_compat shim translates its internal hf_hub_download call.
                pipeline = Pipeline.from_pretrained(
                    settings.diarization_model, use_auth_token=settings.hf_token
                )
                # pyannote returns None (instead of raising) when the download is
                # refused — almost always because the gated model conditions were
                # not accepted/authorized for this HuggingFace account. Probe the
                # real download so we can log the EXACT underlying error (e.g. the
                # 403 GatedRepoError) instead of a vague guess.
                if pipeline is None:
                    detail = self._diagnose_download_failure()
                    raise DiarizationError(
                        f"Could not download the gated pyannote model "
                        f"'{settings.diarization_model}'. {detail} Accept/request "
                        "access with the same HuggingFace account as your token at "
                        "https://hf.co/pyannote/speaker-diarization-3.1 and "
                        "https://hf.co/pyannote/segmentation-3.0, then retry."
                    )
                pipeline.to(torch.device(self.device))
                self._pipeline = pipeline
            except DiarizationError:
                raise
            except Exception as exc:
                logger.exception("Diarization model loading FAILED: %s", exc)
                raise DiarizationError(f"Failed to load diarization model: {exc}") from exc
            logger.info("Diarization model loaded successfully.")
        return self._pipeline

    @staticmethod
    def _diagnose_download_failure() -> str:
        """Return the real reason pyannote could not fetch its config.

        pyannote swallows the underlying HTTP error and returns ``None``; we
        re-attempt the ``config.yaml`` download ourselves to capture the exact
        message (typically a 403 GatedRepoError) for the logs and UI.
        """
        try:
            from huggingface_hub import hf_hub_download

            hf_hub_download(
                settings.diarization_model, "config.yaml", token=settings.hf_token
            )
            return "Download returned no pipeline."  # succeeded now — transient
        except Exception as exc:  # noqa: BLE001 — diagnostic only
            return f"Underlying error: {type(exc).__name__}: {exc}"

    def _diarize_sync(
        self, audio_path: str, num_speakers: Optional[int] = None
    ) -> list[dict[str, Any]]:
        pipeline = self._load_pipeline()
        kwargs: dict[str, Any] = {}
        if num_speakers:
            kwargs["num_speakers"] = num_speakers
        diarization = pipeline(audio_path, **kwargs)

        turns: list[dict[str, Any]] = []
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            turns.append(
                {"start": float(turn.start), "end": float(turn.end), "speaker": str(speaker)}
            )
        turns.sort(key=lambda t: t["start"])
        return turns

    async def diarize(
        self, audio_path: str, num_speakers: Optional[int] = None
    ) -> list[dict[str, Any]]:
        """Return speaker turns sorted by start time."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, partial(self._diarize_sync, audio_path, num_speakers)
        )


def _resolve_device() -> str:
    if settings.whisper_device != "auto":
        return settings.whisper_device
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


_service: Optional[DiarizationService] = None


def get_diarization_service() -> DiarizationService:
    global _service
    if _service is None:
        _service = DiarizationService()
    return _service
