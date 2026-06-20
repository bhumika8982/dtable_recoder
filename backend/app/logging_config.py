"""Central logging configuration.

Call :func:`setup_logging` once at startup so every module's
``logging.getLogger(__name__)`` shares a consistent, timestamped format and the
pipeline's step-by-step logs are visible in the uvicorn console.
"""
from __future__ import annotations

import logging
import os

_CONFIGURED = False

_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_DATEFMT = "%H:%M:%S"


def setup_logging() -> None:
    """Configure root logging idempotently. Honours LOG_LEVEL (default INFO)."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATEFMT))

    root = logging.getLogger()
    root.setLevel(level)
    # Avoid duplicate handlers if uvicorn already attached one.
    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        root.addHandler(handler)

    # Our application loggers always emit at the configured level.
    logging.getLogger("app").setLevel(level)
    _CONFIGURED = True
