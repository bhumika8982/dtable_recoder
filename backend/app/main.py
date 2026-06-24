"""FastAPI application entry point.

Wires up CORS, MongoDB lifecycle, and all routers. Run with:
    uvicorn app.main:app --reload
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings

# If FFMPEG_BIN points to a specific file (not just "ffmpeg"), prepend its
# directory to PATH so whisperx.load_audio — which calls ffmpeg as a bare
# command — can find the same binary that our audio_service uses.
_ffmpeg_bin = settings.ffmpeg_bin
if os.sep in _ffmpeg_bin or "/" in _ffmpeg_bin:
    _ffmpeg_dir = os.path.dirname(os.path.abspath(_ffmpeg_bin))
    if _ffmpeg_dir not in os.environ.get("PATH", "").split(os.pathsep):
        os.environ["PATH"] = _ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
from app.db.mongo import close_mongo_connection, connect_to_mongo, get_database
from app.logging_config import setup_logging
from app.meeting_bot.poller import mb_poller
from app.meeting_bot.repository import MeetingBotRepository
from app.meeting_bot.router import router as meeting_bot_router
from app.routers import exports, meetings, webhooks
from app.services.poller_service import poller
from app.speechbrain_compat import patch_speechbrain_k2

setup_logging()
logger = logging.getLogger(__name__)

# Insert the stub ``k2`` module as early as possible — before WhisperX/pyannote
# (which pull in speechbrain) are ever imported — so speechbrain's optional k2
# integration can't crash diarization model loading later.
patch_speechbrain_k2()


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info("Starting %s ...", settings.app_name)
    await connect_to_mongo()
    logger.info("MongoDB connected.")
    try:
        await MeetingBotRepository(get_database()).ensure_indexes()
    except Exception:  # noqa: BLE001 — index creation is best-effort
        logger.exception("meeting_bot index creation failed (continuing)")
    poller.start()
    mb_poller.start()
    yield
    await mb_poller.stop()
    await poller.stop()
    await close_mongo_connection()
    logger.info("Shutdown complete.")


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(meetings.router)
app.include_router(exports.router)
app.include_router(webhooks.router)
app.include_router(meeting_bot_router)


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok", "app": settings.app_name, "env": settings.environment}
