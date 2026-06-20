"""Shared FastAPI dependencies."""
from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db.mongo import get_database
from app.repositories.meeting_repo import MeetingRepository


def get_db() -> AsyncIOMotorDatabase:
    return get_database()


def get_meeting_repo() -> MeetingRepository:
    return MeetingRepository(get_database())
