"""Application configuration loaded from environment variables.

All settings are read once at import time via a cached ``Settings`` instance.
No secrets are hardcoded; see ``.env.example`` for the full list.
"""
from functools import lru_cache
from typing import Optional

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- App ----
    app_name: str = "Meeting Bot"
    environment: str = "development"
    api_base_url: str = "http://localhost:8000"
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # ---- MongoDB ----
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db_name: str = "meeting_bot"

    # ---- AWS S3 ----
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None
    aws_region: str = "us-east-1"
    s3_bucket: str = "meeting-bot-storage"
    s3_endpoint_url: Optional[str] = None  # set for MinIO / localstack

    # ---- Recall.ai ----
    recall_api_key: Optional[str] = None
    recall_base_url: str = "https://us-west-2.recall.ai/api/v1"
    recall_webhook_secret: Optional[str] = None

    # ---- LLM provider for MOM generation ----
    # "openai" (GPT-4o, paid API) or "groq" (free tier, OpenAI-compatible API).
    llm_provider: str = "openai"

    # ---- OpenAI / GPT-4o ----
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4o"
    openai_embedding_model: str = "text-embedding-3-small"

    # ---- Local embeddings (meeting-bot Ask/Search) ----
    # Multilingual model so Hindi + English content/queries match cross-lingually.
    embedding_model_name: str = "paraphrase-multilingual-MiniLM-L12-v2"

    # ---- Meeting-bot live flow ----
    # Publicly reachable base URL Recall can POST live-transcript webhooks to
    # (e.g. an ngrok URL in dev). Falls back to API_BASE_URL.
    meeting_bot_webhook_base_url: Optional[str] = None

    # ---- Groq (free-tier, OpenAI-compatible) ----
    groq_api_key: Optional[str] = None
    groq_model: str = "llama-3.3-70b-versatile"
    groq_base_url: str = "https://api.groq.com/openai/v1"

    # ---- Gemini (Google, OpenAI-compatible endpoint) ----
    gemini_api_key: Optional[str] = None
    gemini_model: str = "gemini-2.0-flash"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"

    # ---- Deepgram (primary cloud transcription — Nova-3, highest accuracy) ----
    # Get free key at https://console.deepgram.com
    deepgram_api_key: Optional[str] = None
    # "hi" = Hindi/Hinglish, "en" = English, "multi" = auto multilingual (best for Hinglish)
    deepgram_language: str = "hi"

    # ---- AssemblyAI (fallback cloud transcription) ----
    assemblyai_api_key: Optional[str] = None
    # "hi" = Hindi/Hinglish (best for Indian meetings), "en" = English only, blank = auto-detect
    assemblyai_language: Optional[str] = None

    @field_validator("assemblyai_language", mode="before")
    @classmethod
    def _blank_lang_to_none(cls, v):
        if isinstance(v, str) and not v.strip():
            return None
        return v

    # ---- WhisperX ----
    whisper_model: str = "large-v2"
    whisper_device: str = "auto"  # auto | cuda | cpu
    whisper_compute_type: str = "float16"  # float16 (gpu) | int8 (cpu)
    whisper_batch_size: int = 16
    whisper_language: Optional[str] = None  # None => auto-detect
    # Word-level alignment is expensive on CPU and only sharpens speaker
    # assignment. Skip it when diarization is off for a big speed-up.
    whisper_align: bool = True

    # ---- pyannote ----
    # HuggingFace token for pyannote models. Loaded from either HF_TOKEN or
    # HUGGINGFACE_TOKEN in .env.
    hf_token: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("HF_TOKEN", "HUGGINGFACE_TOKEN"),
    )
    diarization_model: str = "pyannote/speaker-diarization-3.1"

    # ---- Storage paths ----
    work_dir: str = "./_work"  # local scratch for downloads / ffmpeg output
    ffmpeg_bin: str = "ffmpeg"

    @field_validator("whisper_language", mode="before")
    @classmethod
    def _blank_to_none(cls, v):
        """Treat WHISPER_LANGUAGE="" (from .env) as None => WhisperX auto-detects.

        An empty string is an invalid language code for WhisperX, so it must
        become None rather than be passed through.
        """
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
