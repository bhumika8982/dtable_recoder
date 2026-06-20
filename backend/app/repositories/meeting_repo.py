"""Repository for meeting documents and their derived artifacts.

All artifacts (transcript, MOM, extraction) are keyed by ``meeting_id`` and
live in dedicated collections so each can be fetched independently by the UI.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.models.common import serialize_doc, to_object_id
from app.models.enums import MeetingStatus


def _now() -> datetime:
    return datetime.now(timezone.utc)


class MeetingRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    # ---- meetings ---- #
    async def create(self, data: dict[str, Any]) -> dict[str, Any]:
        doc = {
            **data,
            "status": MeetingStatus.CREATED.value,
            "created_at": _now(),
            "updated_at": _now(),
        }
        result = await self.db.meetings.insert_one(doc)
        doc["_id"] = result.inserted_id
        return serialize_doc(doc)

    async def get(self, meeting_id: str) -> Optional[dict[str, Any]]:
        doc = await self.db.meetings.find_one({"_id": to_object_id(meeting_id)})
        return serialize_doc(doc)

    async def get_by_bot_id(self, bot_id: str) -> Optional[dict[str, Any]]:
        doc = await self.db.meetings.find_one({"recall_bot_id": bot_id})
        return serialize_doc(doc)

    async def list(self, limit: int = 100) -> list[dict[str, Any]]:
        cursor = self.db.meetings.find().sort("created_at", -1).limit(limit)
        return [serialize_doc(d) for d in await cursor.to_list(length=limit)]

    async def update(self, meeting_id: str, fields: dict[str, Any]) -> None:
        fields = {**fields, "updated_at": _now()}
        await self.db.meetings.update_one(
            {"_id": to_object_id(meeting_id)}, {"$set": fields}
        )

    async def set_status(
        self, meeting_id: str, status: MeetingStatus, error: str | None = None
    ) -> None:
        fields: dict[str, Any] = {"status": status.value}
        if error is not None:
            fields["error"] = error
        await self.update(meeting_id, fields)

    async def delete(self, meeting_id: str) -> bool:
        """Delete a meeting and its derived artifacts. Returns True if it existed."""
        result = await self.db.meetings.delete_one({"_id": to_object_id(meeting_id)})
        # Remove the transcript/MOM keyed by this meeting (no-op if absent).
        await self.db.transcripts.delete_many({"meeting_id": meeting_id})
        await self.db.moms.delete_many({"meeting_id": meeting_id})
        return result.deleted_count > 0

    # ---- transcript ---- #
    async def save_transcript(self, meeting_id: str, transcript: dict[str, Any]) -> None:
        await self.db.transcripts.update_one(
            {"meeting_id": meeting_id},
            {"$set": {**transcript, "meeting_id": meeting_id, "updated_at": _now()}},
            upsert=True,
        )

    async def get_transcript(self, meeting_id: str) -> Optional[dict[str, Any]]:
        doc = await self.db.transcripts.find_one({"meeting_id": meeting_id})
        return serialize_doc(doc)

    # ---- MOM ---- #
    async def save_mom(self, meeting_id: str, mom: dict[str, Any]) -> None:
        await self.db.moms.update_one(
            {"meeting_id": meeting_id},
            {"$set": {**mom, "meeting_id": meeting_id, "updated_at": _now()}},
            upsert=True,
        )

    async def get_mom(self, meeting_id: str) -> Optional[dict[str, Any]]:
        doc = await self.db.moms.find_one({"meeting_id": meeting_id})
        return serialize_doc(doc)
