"""Compatibility shim for speechbrain's optional ``k2`` integration.

pyannote.audio's speaker-diarization-3.1 pipeline loads a speechbrain-based
embedding model. Newer speechbrain ships a ``speechbrain.integrations.k2_fsa``
package that does ``import k2`` at import time. ``k2`` (k2-fsa) is an optional
ASR dependency that is effectively un-installable on Windows, so the import
raises ``ModuleNotFoundError: No module named 'k2'``.

The breakage is intermittent: it only fires when something (e.g. an internal
warning's ``inspect.stack()`` walk) touches speechbrain's lazy module objects,
triggering the lazy ``k2_fsa`` import — which then crashes pipeline loading with
a confusing ``'NoneType' object has no attribute 'eval'``.

We never use k2 (diarization doesn't need it). Registering a tiny stub ``k2``
module makes the harmless ``import k2`` succeed so speechbrain's lazy machinery
doesn't blow up. Call once before loading pyannote.
"""
from __future__ import annotations

import logging
import sys
import types

logger = logging.getLogger(__name__)

_patched = False


def patch_speechbrain_k2() -> None:
    """Insert a stub ``k2`` module if k2 is not installed (idempotent)."""
    global _patched
    if _patched:
        return

    # If a real k2 is installed, leave it alone.
    try:
        import k2  # noqa: F401

        _patched = True
        return
    except Exception:  # noqa: BLE001 — any failure means k2 is unusable; stub it
        pass

    stub = types.ModuleType("k2")
    stub.__version__ = "0.0.0-stub"
    # Mark it so it's obvious in introspection that this is not the real k2.
    stub.__doc__ = "Stub k2 module injected by app.speechbrain_compat (k2 not installed)."
    sys.modules.setdefault("k2", stub)

    _patched = True
    logger.info("Inserted stub 'k2' module (real k2 not installed; diarization doesn't need it).")
