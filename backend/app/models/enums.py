"""Shared enumerations for meeting lifecycle and processing state."""
from enum import Enum


class MeetingStatus(str, Enum):
    CREATED = "created"            # meeting record created
    BOT_SCHEDULED = "bot_scheduled"  # Recall bot dispatched to call
    IN_CALL = "in_call"           # bot is in the meeting
    RECORDING_READY = "recording_ready"  # Recall finished, media available
    DOWNLOADING = "downloading"
    EXTRACTING_AUDIO = "extracting_audio"
    TRANSCRIBING = "transcribing"
    DIARIZING = "diarizing"
    MERGING = "merging"
    GENERATING_MOM = "generating_mom"
    COMPLETED = "completed"
    FAILED = "failed"
