"""Compatibility shim for PyTorch >= 2.6.

PyTorch 2.6 changed ``torch.load``'s default to ``weights_only=True``, which
refuses to unpickle the non-tensor objects (e.g. ``omegaconf.ListConfig``) baked
into the official WhisperX VAD and pyannote diarization checkpoints. Those models
are downloaded from trusted sources (HuggingFace), so we restore the previous
behaviour by defaulting ``weights_only=False`` when the caller didn't set it.

Call :func:`patch_torch_load` once before loading any WhisperX/pyannote model.
"""
from __future__ import annotations

import functools
import logging

logger = logging.getLogger(__name__)

_patched = False


def patch_torch_load() -> None:
    """Idempotently make ``torch.load`` default to ``weights_only=False``."""
    global _patched
    if _patched:
        return

    import torch

    _orig_load = torch.load

    @functools.wraps(_orig_load)
    def _load(*args, **kwargs):
        # Force False: some callers (e.g. lightning_fabric's checkpoint loader)
        # pass weights_only=True explicitly, so setdefault wouldn't help.
        kwargs["weights_only"] = False
        return _orig_load(*args, **kwargs)

    torch.load = _load
    _patched = True
    logger.info(
        "Patched torch.load(weights_only=False) for trusted WhisperX/pyannote checkpoints."
    )
