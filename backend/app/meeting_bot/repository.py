"""MongoDB access for the meeting-bot flow.

All artifacts are keyed by ``meeting_id`` and split by ``source`` (live / audio /
video) so the three transcripts and three MoMs never overwrite each other.
Reuses the shared Motor connection from ``app.db.mongo``.
"""
from __future__ import annotations

from typing import Any, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.meeting_bot import models as M
from app.meeting_bot.utils import now


class MeetingBotRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    # ------------------------------------------------------------------ #
    # Meetings
    # ------------------------------------------------------------------ #
    async def create_meeting(self, data: dict[str, Any]) -> dict[str, Any]:
        doc = {
            **data,
            "status": M.MeetingStatus.CREATED.value,
            "bot_status": M.BotStatus.NOT_JOINED.value,
            "live_transcript_status": M.TranscriptStatus.NOT_STARTED.value,
            "recording_status": M.RecordingStatus.NOT_STARTED.value,
            "audio_recording_status": M.RecordingStatus.NOT_STARTED.value,
            "video_recording_status": M.RecordingStatus.NOT_STARTED.value,
            "live_mom_status": M.MomStatus.NOT_STARTED.value,
            "audio_transcript_status": M.TranscriptStatus.NOT_STARTED.value,
            "ai_transcript_status": M.TranscriptStatus.NOT_STARTED.value,
            "audio_mom_status": M.MomStatus.NOT_STARTED.value,
            "video_transcript_status": M.TranscriptStatus.NOT_STARTED.value,
            "video_mom_status": M.MomStatus.NOT_STARTED.value,
            "audio_recording_url": None,
            "video_recording_url": None,
            "created_at": now(),
            "updated_at": now(),
            "completed_at": None,
        }
        res = await self.db[M.MEETINGS].insert_one(doc)
        return await self.get_meeting(str(res.inserted_id))

    async def get_meeting(self, meeting_id: str) -> Optional[dict[str, Any]]:
        from app.models.common import serialize_doc, to_object_id

        doc = await self.db[M.MEETINGS].find_one({"_id": to_object_id(meeting_id)})
        return serialize_doc(doc)

    async def get_meeting_by_bot(self, bot_id: str) -> Optional[dict[str, Any]]:
        from app.models.common import serialize_doc

        doc = await self.db[M.MEETINGS].find_one({"bot_id": bot_id})
        return serialize_doc(doc)

    async def list_meetings(self, limit: int = 100) -> list[dict[str, Any]]:
        from app.models.common import serialize_doc

        cur = self.db[M.MEETINGS].find().sort("created_at", -1).limit(limit)
        return [serialize_doc(d) for d in await cur.to_list(length=limit)]

    async def update_meeting(self, meeting_id: str, fields: dict[str, Any]) -> None:
        from app.models.common import to_object_id

        await self.db[M.MEETINGS].update_one(
            {"_id": to_object_id(meeting_id)},
            {"$set": {**fields, "updated_at": now()}},
        )

    async def delete_meeting(self, meeting_id: str) -> bool:
        from app.models.common import to_object_id

        res = await self.db[M.MEETINGS].delete_one({"_id": to_object_id(meeting_id)})
        await self.db[M.TRANSCRIPT_CHUNKS].delete_many({"meeting_id": meeting_id})
        await self.db[M.MOMS].delete_many({"meeting_id": meeting_id})
        await self.db[M.RECORDINGS].delete_many({"meeting_id": meeting_id})
        return res.deleted_count > 0

    # ------------------------------------------------------------------ #
    # Transcript chunks (live / audio / video)
    # ------------------------------------------------------------------ #
    async def add_chunk(self, chunk: dict[str, Any]) -> bool:
        """Insert one transcript chunk. Returns False if it's a duplicate.

        Idempotency: a unique index on (meeting_id, source, chunk_id) drops
        duplicate live-webhook deliveries.
        """
        from pymongo.errors import DuplicateKeyError

        try:
            await self.db[M.TRANSCRIPT_CHUNKS].insert_one({**chunk, "created_at": now()})
            return True
        except DuplicateKeyError:
            return False

    async def replace_chunks(
        self, meeting_id: str, source: str, chunks: list[dict[str, Any]]
    ) -> None:
        """Replace all chunks for a (meeting, source) — used by audio/video re-runs."""
        await self.db[M.TRANSCRIPT_CHUNKS].delete_many(
            {"meeting_id": meeting_id, "source": source}
        )
        if chunks:
            await self.db[M.TRANSCRIPT_CHUNKS].insert_many(
                [{**c, "created_at": now()} for c in chunks]
            )

    async def get_chunks(
        self, meeting_id: str, source: str, skip: int = 0, limit: int = 1000
    ) -> list[dict[str, Any]]:
        from app.models.common import serialize_doc

        cur = (
            self.db[M.TRANSCRIPT_CHUNKS]
            .find({"meeting_id": meeting_id, "source": source})
            .sort([("chunk_index", 1), ("start_time", 1)])
            .skip(skip)
            .limit(limit)
        )
        return [serialize_doc(d) for d in await cur.to_list(length=limit)]

    async def count_chunks(self, meeting_id: str, source: str) -> int:
        return await self.db[M.TRANSCRIPT_CHUNKS].count_documents(
            {"meeting_id": meeting_id, "source": source}
        )

    async def save_chunk_embeddings(
        self, meeting_id: str, source: str, chunks: list[dict[str, Any]]
    ) -> None:
        """Persist the ``embedding`` vector computed for each chunk."""
        for c in chunks:
            if c.get("embedding") is None:
                continue
            await self.db[M.TRANSCRIPT_CHUNKS].update_one(
                {"meeting_id": meeting_id, "source": source, "chunk_id": c["chunk_id"]},
                {"$set": {"embedding": c["embedding"], "embedding_id": c.get("chunk_id")}},
            )

    async def get_embedded_chunks(self, meeting_id: str) -> list[dict[str, Any]]:
        """All chunks (any source) that have an embedding, for semantic search."""
        from app.models.common import serialize_doc

        cur = self.db[M.TRANSCRIPT_CHUNKS].find(
            {"meeting_id": meeting_id, "embedding": {"$exists": True, "$ne": None}}
        )
        return [serialize_doc(d) for d in await cur.to_list(length=100000)]

    # ------------------------------------------------------------------ #
    # MoMs (live / audio / video)
    # ------------------------------------------------------------------ #
    async def save_mom(self, meeting_id: str, source: str, mom: dict[str, Any]) -> None:
        await self.db[M.MOMS].update_one(
            {"meeting_id": meeting_id, "source": source},
            {"$set": {**mom, "meeting_id": meeting_id, "source": source, "generated_at": now()}},
            upsert=True,
        )

    async def get_mom(self, meeting_id: str, source: str) -> Optional[dict[str, Any]]:
        from app.models.common import serialize_doc

        doc = await self.db[M.MOMS].find_one({"meeting_id": meeting_id, "source": source})
        return serialize_doc(doc)

    # ------------------------------------------------------------------ #
    # Recordings
    # ------------------------------------------------------------------ #
    async def save_recording(self, meeting_id: str, rec_type: str, rec: dict[str, Any]) -> None:
        await self.db[M.RECORDINGS].update_one(
            {"meeting_id": meeting_id, "type": rec_type},
            {"$set": {**rec, "meeting_id": meeting_id, "type": rec_type, "created_at": now()}},
            upsert=True,
        )

    # ------------------------------------------------------------------ #
    # Webhook idempotency
    # ------------------------------------------------------------------ #
    async def seen_webhook(self, event_id: str) -> bool:
        """Record a webhook event id; return True if it was already processed."""
        from pymongo.errors import DuplicateKeyError

        try:
            await self.db[M.WEBHOOK_EVENTS].insert_one({"_id": event_id, "at": now()})
            return False
        except DuplicateKeyError:
            return True

    # ------------------------------------------------------------------ #
    # Indexes
    # ------------------------------------------------------------------ #
    async def ensure_indexes(self) -> None:
        await self.db[M.MEETINGS].create_index("bot_id")
        await self.db[M.MEETINGS].create_index("status")
        await self.db[M.TRANSCRIPT_CHUNKS].create_index(
            [("meeting_id", 1), ("source", 1), ("chunk_id", 1)], unique=True
        )
        await self.db[M.TRANSCRIPT_CHUNKS].create_index([("meeting_id", 1), ("source", 1)])
        await self.db[M.MOMS].create_index(
            [("meeting_id", 1), ("source", 1)], unique=True
        )
        await self.db[M.RECORDINGS].create_index(
            [("meeting_id", 1), ("type", 1)], unique=True
        )
