"""Prompt templates for GPT-4o MOM generation.

Kept in one module so wording can be tuned without touching service logic.
The prompt instructs the model to ground output strictly in the transcript and
to return strict JSON matching our MOM schema.
"""

MOM_SYSTEM = """You are an expert meeting-minutes assistant. You write accurate, \
concise Minutes of Meeting (MOM) grounded strictly in the provided transcript. \
Never invent attendees, decisions, action items, or facts not present in the \
transcript. Return ONLY valid JSON."""

MOM_USER_TEMPLATE = """Produce Minutes of Meeting from the transcript below.

Return JSON with exactly these keys:
{{
  "summary": "a concise paragraph overview of the meeting",
  "key_points": ["key discussion point", ...],
  "action_items": ["action item / task agreed in the meeting", ...],
  "next_steps": ["next step", ...],
  "attendees": ["speaker label or name", ...]
}}

Only include action items that are explicitly agreed or assigned in the
transcript; if there are none, return an empty array. Use only the speakers that
actually appear. Keep lists focused (max ~10 items).

TRANSCRIPT:
{transcript}"""
