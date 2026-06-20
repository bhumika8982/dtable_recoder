"""GPT-4o generation of Minutes of Meeting (MOM) from a transcript.

Transcripts can exceed the context window, so very long transcripts are
truncated to a character budget. For production you would chunk-and-map-reduce;
this keeps the flow simple and within the project's no-queue constraint.
"""
from __future__ import annotations

from typing import Any

from app.services.llm_service import LLMService
from app.services.prompts import MOM_SYSTEM, MOM_USER_TEMPLATE

# ~ conservative budget so the prompt + transcript fit comfortably in context.
MAX_TRANSCRIPT_CHARS = 48000


def _prepare_transcript(full_text: str) -> str:
    if len(full_text) <= MAX_TRANSCRIPT_CHARS:
        return full_text
    head = full_text[: int(MAX_TRANSCRIPT_CHARS * 0.6)]
    tail = full_text[-int(MAX_TRANSCRIPT_CHARS * 0.4):]
    return f"{head}\n...\n[transcript truncated]\n...\n{tail}"


class GenerationService:
    def __init__(self, llm: LLMService | None = None):
        self.llm = llm or LLMService()

    @staticmethod
    def _empty_mom() -> dict[str, Any]:
        return {
            "summary": "",
            "key_points": [],
            "action_items": [],
            "next_steps": [],
            "attendees": [],
        }

    async def generate_mom(self, full_text: str) -> dict[str, Any]:
        if not full_text or not full_text.strip():
            return self._empty_mom()  # never invent a summary from nothing
        transcript = _prepare_transcript(full_text)
        data = await self.llm.complete_json(
            MOM_SYSTEM, MOM_USER_TEMPLATE.format(transcript=transcript)
        )
        return {
            "summary": data.get("summary", ""),
            "key_points": data.get("key_points", []),
            "action_items": data.get("action_items", []),
            "next_steps": data.get("next_steps", []),
            "attendees": data.get("attendees", []),
        }
