"""Pydantic schemas for meetings and processing artifacts.

These define the API contract (requests/responses) and the document shape we
persist in MongoDB. The system supports three features: Recording, Transcript,
and MOM.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.common import PyObjectId
from app.models.enums import MeetingStatus


# --------------------------------------------------------------------------- #
# Meetings
# --------------------------------------------------------------------------- #
class MeetingCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    meeting_url: str = Field(..., description="Zoom/Meet/Teams join URL")
    bot_name: str = "Meeting Bot"
    join_at: Optional[datetime] = Field(
        default=None, description="Schedule the bot to join at this time (UTC)."
    )
    num_speakers: Optional[int] = Field(
        default=None,
        ge=1,
        le=20,
        description="Expected number of speakers; constrains diarization. Leave "
        "empty to auto-detect.",
    )


class MeetingOut(BaseModel):
    id: PyObjectId = Field(alias="_id")
    title: str
    meeting_url: str
    bot_name: str = "Meeting Bot"
    status: MeetingStatus = MeetingStatus.CREATED
    recall_bot_id: Optional[str] = None
    error: Optional[str] = None
    # S3 keys for stored artifacts
    recording_s3_key: Optional[str] = None
    audio_s3_key: Optional[str] = None
    transcript_s3_key: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"populate_by_name": True}


# --------------------------------------------------------------------------- #
# Transcript
# --------------------------------------------------------------------------- #
class TranscriptSegment(BaseModel):
    start: float
    end: float
    speaker: str = "UNKNOWN"
    speaker_label: Optional[str] = None  # readable name, e.g. "Speaker 1"
    text: str


class TranscriptOut(BaseModel):
    meeting_id: str
    language: Optional[str] = None
    segments: list[TranscriptSegment] = []
    full_text: str = ""
    formatted: str = ""  # "[HH:MM:SS] Speaker N: text" lines


# --------------------------------------------------------------------------- #
# MOM (Minutes of Meeting)
# --------------------------------------------------------------------------- #
class MomOut(BaseModel):
    meeting_id: str
    summary: str = ""
    key_points: list[str] = []
    action_items: list[str] = []
    next_steps: list[str] = []
    attendees: list[str] = []
