"""MongoDB connection management using Motor (async driver).

A single ``AsyncIOMotorClient`` is created at startup and shared across the app.
Repositories receive the database handle via :func:`get_database`.
"""
from __future__ import annotations

import asyncio
import logging

import certifi
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import PyMongoError

from app.config import settings

logger = logging.getLogger(__name__)


class _Mongo:
    client: AsyncIOMotorClient | None = None
    db: AsyncIOMotorDatabase | None = None


_mongo = _Mongo()


async def connect_to_mongo() -> None:
    """Initialise the global Mongo client and ensure indexes.

    Uses certifi's CA bundle so TLS verification works reliably on Windows
    (where the system cert store is often the cause of Atlas handshake errors),
    and fails fast with an actionable message instead of a long traceback.
    """
    is_atlas = "mongodb+srv" in settings.mongo_uri or "mongodb.net" in settings.mongo_uri
    kwargs: dict = {"serverSelectionTimeoutMS": 8000}
    if is_atlas or settings.mongo_uri.startswith("mongodb+srv"):
        # Atlas/SRV connections are TLS; pin the CA bundle explicitly.
        kwargs["tlsCAFile"] = certifi.where()

    _mongo.client = AsyncIOMotorClient(settings.mongo_uri, tz_aware=True, **kwargs)
    _mongo.db = _mongo.client[settings.mongo_db_name]

    # Retry the initial connection a few times: free-tier Atlas clusters briefly
    # have "no primary" during elections/resumes, which would otherwise crash
    # startup. Transient blips recover within a few seconds.
    attempts = 5
    last_exc: PyMongoError | None = None
    for i in range(1, attempts + 1):
        try:
            await _mongo.client.admin.command("ping")
            await _ensure_indexes(_mongo.db)
            if i > 1:
                logger.info("MongoDB connected on attempt %d.", i)
            return
        except PyMongoError as exc:
            last_exc = exc
            logger.warning(
                "MongoDB connection attempt %d/%d failed (%s). Retrying...",
                i, attempts, type(exc).__name__,
            )
            await asyncio.sleep(min(2 * i, 8))

    await close_mongo_connection()
    hint = (
        "Could not connect to MongoDB after retries. Usually a network/Atlas "
        "issue, not a code bug.\n"
        "  - Most common: your current network's public IP is NOT in the Atlas "
        "IP Access List. Switching WiFi/hotspot changes your IP. Add it (or "
        "0.0.0.0/0 for development) at Atlas -> Network Access -> IP Access List.\n"
        "  - Free-tier (M0) clusters can also be paused/electing; wait a moment "
        "and restart.\n"
        "  - Also check: the network isn't blocking outbound port 27017, and the "
        "MONGO_URI credentials are correct.\n"
        f"Underlying error: {type(last_exc).__name__}: {last_exc}"
    )
    logger.error(hint)
    raise RuntimeError(hint) from last_exc


async def close_mongo_connection() -> None:
    if _mongo.client is not None:
        _mongo.client.close()
        _mongo.client = None
        _mongo.db = None


def get_database() -> AsyncIOMotorDatabase:
    if _mongo.db is None:
        raise RuntimeError("Mongo is not connected. Call connect_to_mongo() first.")
    return _mongo.db


async def _ensure_indexes(db: AsyncIOMotorDatabase) -> None:
    await db.meetings.create_index("recall_bot_id")
    await db.meetings.create_index("status")
    await db.transcripts.create_index("meeting_id", unique=True)
    await db.moms.create_index("meeting_id", unique=True)
