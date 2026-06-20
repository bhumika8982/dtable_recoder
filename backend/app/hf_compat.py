"""Compatibility shim for huggingface_hub >= 1.x.

huggingface_hub removed the deprecated ``use_auth_token`` argument from
``hf_hub_download`` (only ``token`` remains). pyannote.audio 3.3.2 still calls
``hf_hub_download(..., use_auth_token=...)`` internally when loading the
diarization pipeline / models, which raises::

    hf_hub_download() got an unexpected keyword argument 'use_auth_token'

and breaks diarization (and therefore transcript + MOM generation).

:func:`patch_hf_hub_download` wraps ``hf_hub_download`` so that a passed
``use_auth_token`` is transparently forwarded as ``token``. It also fixes any
modules (e.g. pyannote) that already imported the symbol by reference.

Call it once before importing/loading WhisperX or pyannote.
"""
from __future__ import annotations

import functools
import logging
import sys

logger = logging.getLogger(__name__)

_patched = False


def patch_hf_hub_download() -> None:
    """Idempotently translate the deprecated ``use_auth_token`` arg to ``token``."""
    global _patched
    if _patched:
        return

    import huggingface_hub

    orig = huggingface_hub.hf_hub_download
    if getattr(orig, "_use_auth_token_shim", False):
        _patched = True
        return

    @functools.wraps(orig)
    def patched(*args, **kwargs):
        if "use_auth_token" in kwargs:
            token = kwargs.pop("use_auth_token")
            kwargs.setdefault("token", token)
        return orig(*args, **kwargs)

    patched._use_auth_token_shim = True
    huggingface_hub.hf_hub_download = patched

    # pyannote does `from huggingface_hub import hf_hub_download` at import time,
    # so any already-imported module holds a reference to the original. Rebind it.
    #
    # IMPORTANT: probe ``module.__dict__`` directly rather than ``getattr``. Some
    # packages (notably ``transformers``) use a lazy ``__getattr__`` that imports
    # heavy submodules on attribute access; probing with ``getattr`` would trigger
    # e.g. ``transformers.models.aria`` -> ``import torchvision`` and crash the
    # whole patch with ModuleNotFoundError before WhisperX ever runs. Reading
    # ``__dict__`` only sees names already bound via ``from ... import ...``.
    for module in list(sys.modules.values()):
        if module is None:
            continue
        try:
            module_dict = module.__dict__
        except AttributeError:  # some module-like objects have no __dict__
            continue
        if module_dict.get("hf_hub_download") is orig:
            try:
                module_dict["hf_hub_download"] = patched
            except Exception:  # noqa: BLE001 — best effort
                pass

    _patched = True
    logger.info("Patched hf_hub_download: use_auth_token -> token (huggingface_hub compat).")
