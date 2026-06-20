"""Structured Minutes-of-Meeting generation for the meeting-bot flow.

Reuses the existing provider-agnostic ``LLMService`` (Groq by default, OpenAI
optional) and produces the rich, production MoM schema. Long transcripts are
truncated to a safe budget; output is grounded strictly in the transcript.
"""
from __future__ import annotations

import logging
from typing import Any

from app.services.llm_service import LLMService

logger = logging.getLogger(__name__)

MAX_CHARS = 48000

_SYSTEM = (
    "You are an expert meeting-minutes assistant for bilingual (English + Hindi) "
    "meetings. The transcript may mix English and Hindi (Devanagari or romanized). "
    "ALWAYS write the entire Minutes of Meeting in clear, professional ENGLISH, "
    "translating any Hindi content to English while preserving the exact meaning, "
    "names and numbers. Keep people's names as spoken. Stay STRICTLY grounded in "
    "the transcript — never invent attendees, decisions, owners, deadlines or "
    "facts. Return ONLY valid JSON."
)

_USER = """Produce Minutes of Meeting as JSON with EXACTLY these keys:
{{
  "summary": "concise paragraph overview",
  "key_discussion_points": ["..."],
  "decisions_taken": ["..."],
  "action_items": [
    {{"task": "...", "owner": "name or null", "deadline": "text or null",
      "priority": "high|medium|low or null", "source_sentence": "exact transcript line"}}
  ],
  "pending_tasks": ["..."],
  "next_steps": ["..."],
  "speaker_wise_notes": {{"Speaker or Name": ["point", "..."]}}
}}

Rules:
- Write ALL fields in English (translate Hindi to English). Keep names as-is.
- "source_sentence" is the exact original transcript line (may be Hindi/English).
- Only include items explicitly present in the transcript; use [] / {{}} if none.
- owner/deadline/priority must come from the transcript, else null.
- Keep lists focused (max ~12 items each).

TRANSCRIPT (may contain English and Hindi):
{transcript}"""


def _empty() -> dict[str, Any]:
    return {
        "summary": "",
        "key_discussion_points": [],
        "decisions_taken": [],
        "action_items": [],
        "pending_tasks": [],
        "next_steps": [],
        "speaker_wise_notes": {},
    }


def _prepare(text: str) -> str:
    if len(text) <= MAX_CHARS:
        return text
    head = text[: int(MAX_CHARS * 0.6)]
    tail = text[-int(MAX_CHARS * 0.4):]
    return f"{head}\n...\n[transcript truncated]\n...\n{tail}"


class MomService:
    def __init__(self, llm: LLMService | None = None):
        self.llm = llm or LLMService()

    async def generate(self, transcript_text: str) -> dict[str, Any]:
        """Generate the structured MoM. Empty transcript -> empty MoM (no hallucination)."""
        if not transcript_text or not transcript_text.strip():
            logger.warning("MoM requested on empty transcript — returning empty MoM.")
            return _empty()
        data = await self.llm.complete_json(_SYSTEM, _USER.format(transcript=_prepare(transcript_text)))
        out = _empty()
        for key in out:
            if key in data and data[key] is not None:
                out[key] = data[key]
        # Normalise action items into dicts.
        norm = []
        for ai in out["action_items"]:
            if isinstance(ai, str):
                norm.append({"task": ai, "owner": None, "deadline": None, "priority": None, "source_sentence": None})
            elif isinstance(ai, dict):
                norm.append({
                    "task": ai.get("task", ""),
                    "owner": ai.get("owner"),
                    "deadline": ai.get("deadline"),
                    "priority": ai.get("priority"),
                    "source_sentence": ai.get("source_sentence"),
                })
        out["action_items"] = norm
        return out
