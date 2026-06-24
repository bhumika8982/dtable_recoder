"""Status enums and constants for the advanced meeting-bot flow.

These are intentionally separate from ``app.models.enums`` so the new flow can
evolve independently without affecting the existing ``/api/meetings`` pipeline.
"""
from __future__ import annotations

from enum import Enum


class Source(str, Enum):
    """Origin of a transcript / MoM artifact."""

    LIVE = "live"
    AUDIO = "audio"
    VIDEO = "video"
    AI = "ai"  # AI-proofread version of the audio transcript


class MeetingStatus(str, Enum):
    CREATED = "created"
    JOINING = "joining"
    WAITING_FOR_ADMIT = "waiting_for_admit"
    LIVE = "live"
    PROCESSING = "processing"  # meeting ended; preparing recordings/transcript/MoM
    COMPLETED = "completed"
    FAILED = "failed"


class BotStatus(str, Enum):
    NOT_JOINED = "not_joined"
    JOINING = "joining"
    WAITING = "waiting"
    JOINED = "joined"
    LEFT = "left"
    REMOVED = "removed"
    FAILED = "failed"


class RecordingStatus(str, Enum):
    NOT_STARTED = "not_started"
    RECORDING = "recording"
    UPLOADING = "uploading"
    UPLOADED = "uploaded"
    FAILED = "failed"


class TranscriptStatus(str, Enum):
    NOT_STARTED = "not_started"
    GENERATING = "generating"
    GENERATED = "generated"
    FAILED = "failed"


class MomStatus(str, Enum):
    NOT_STARTED = "not_started"
    GENERATING = "generating"
    GENERATED = "generated"
    FAILED = "failed"


# Collection names (kept distinct from the legacy collections).
MEETINGS = "mb_meetings"
TRANSCRIPT_CHUNKS = "mb_transcript_chunks"
RECORDINGS = "mb_recordings"
MOMS = "mb_moms"
WEBHOOK_EVENTS = "mb_webhook_events"  # idempotency ledger


# S3 key templates (single source of truth for the layout).
def s3_key(kind: str, meeting_id: str) -> str:
    return {
        "video": f"video-recordings/{meeting_id}.mp4",
        "audio": f"audio-recordings/{meeting_id}.mp3",
        "transcript_live": f"transcripts/live/{meeting_id}.txt",
        "transcript_audio": f"transcripts/audio/{meeting_id}.txt",
        "transcript_video": f"transcripts/video/{meeting_id}.txt",
        "mom_live": f"mom/live/{meeting_id}.json",
        "mom_audio": f"mom/audio/{meeting_id}.json",
        "mom_video": f"mom/video/{meeting_id}.json",
        "mom_ai": f"mom/ai/{meeting_id}.json",
    }[kind]
