"""Pydantic request/response models for the meeting-bot API."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.meeting_bot.models import Source


# --------------------------------------------------------------------------- #
# Requests
# --------------------------------------------------------------------------- #
class MeetingCreate(BaseModel):
    meeting_title: str = Field(..., min_length=1, max_length=300)
    meeting_link: str = Field(..., description="Zoom / Meet / Teams join URL")
    participants: Optional[list[str]] = None
    created_by: Optional[str] = None
    # The display name the bot joins meetings with.
    bot_name: str = "D-Table"
    num_speakers: Optional[int] = Field(default=None, ge=1, le=50)


# --------------------------------------------------------------------------- #
# Responses
# --------------------------------------------------------------------------- #
class MeetingCreated(BaseModel):
    meeting_id: str
    bot_id: Optional[str] = None
    status: str


class Correction(BaseModel):
    wrong: str
    right: str


class TranscriptChunkOut(BaseModel):
    chunk_id: str
    meeting_id: str
    source: Source
    speaker_name: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    text: str
    corrected_text: Optional[str] = None
    corrections: list[Correction] = []
    is_final: bool = True
    chunk_index: int = 0
    created_at: Optional[datetime] = None


class TranscriptOut(BaseModel):
    meeting_id: str
    source: Source
    status: str
    text: str = ""
    chunks: list[TranscriptChunkOut] = []
    total: int = 0


class ActionItem(BaseModel):
    task: str
    owner: Optional[str] = None
    deadline: Optional[str] = None
    priority: Optional[str] = None
    source_sentence: Optional[str] = None


class MomOut(BaseModel):
    meeting_id: str
    source: Source
    status: str
    summary: str = ""
    key_discussion_points: list[str] = []
    decisions_taken: list[str] = []
    action_items: list[ActionItem] = []
    pending_tasks: list[str] = []
    next_steps: list[str] = []
    speaker_wise_notes: dict[str, Any] = {}
    generated_at: Optional[datetime] = None


class RecordingsOut(BaseModel):
    meeting_id: str
    audio_recording_url: Optional[str] = None
    video_recording_url: Optional[str] = None
    audio_recording_status: str
    video_recording_status: str


class ActionState(BaseModel):
    """What the frontend is allowed to trigger right now."""

    can_generate_live_mom: bool = False
    can_generate_audio_transcript: bool = False
    can_generate_ai_transcript: bool = False
    can_generate_audio_mom: bool = False
    can_generate_video_transcript: bool = False
    can_generate_video_mom: bool = False


class MeetingDetail(BaseModel):
    meeting_id: str
    meeting_title: str
    meeting_link: Optional[str] = None
    created_by: Optional[str] = None
    bot_id: Optional[str] = None
    status: str
    bot_status: str
    live_transcript_status: str
    recording_status: str
    audio_recording_status: str
    video_recording_status: str
    live_mom_status: str
    audio_transcript_status: str
    ai_transcript_status: str = "not_started"
    audio_mom_status: str
    video_transcript_status: str
    video_mom_status: str
    audio_recording_url: Optional[str] = None
    video_recording_url: Optional[str] = None
    embeddings_status: str = "not_started"
    embedded_chunks: int = 0
    audio_transcript_language: Optional[str] = None
    video_transcript_language: Optional[str] = None
    error: Optional[str] = None
    available_actions: ActionState
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class JobAccepted(BaseModel):
    """Returned by long-running trigger endpoints (202)."""

    meeting_id: str
    job: str
    status: str


class TranslateRequest(BaseModel):
    target_language: str = Field(..., min_length=2, max_length=10)


class TranslateResponse(BaseModel):
    meeting_id: str
    source: Source
    lang: str
    chunks: list[TranscriptChunkOut]


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)
    top_k: int = Field(default=8, ge=1, le=20)


class AskSource(BaseModel):
    source: str
    speaker_name: Optional[str] = None
    start_time: Optional[float] = None
    text: str
    score: float


class AskResponse(BaseModel):
    meeting_id: str
    question: str
    answer: str
    sources: list[AskSource] = []
