"""Tests for GPT-4o MOM generation.

The LLM is faked so no API key or network is needed; we assert the service
shapes the model output into our MOM schema correctly and never invents a
summary from an empty transcript.
"""
import pytest

from app.services.generation_service import GenerationService


class FakeLLM:
    """Returns canned JSON keyed by a marker in the user prompt."""

    def __init__(self, responses):
        self.responses = responses

    async def complete_json(self, system, user, temperature=0.2):
        if "Minutes of Meeting" in user:
            return self.responses["mom"]
        return {}


@pytest.mark.asyncio
async def test_generate_mom():
    llm = FakeLLM(
        {
            "mom": {
                "summary": "We planned the sprint.",
                "key_points": ["ship login"],
                "action_items": ["assign tickets to the team"],
                "next_steps": ["schedule review"],
                "attendees": ["Speaker 1"],
            }
        }
    )
    svc = GenerationService(llm=llm)
    mom = await svc.generate_mom("[00:00:00] Speaker 1: We planned the sprint.")
    assert mom["summary"] == "We planned the sprint."
    assert mom["action_items"] == ["assign tickets to the team"]
    assert mom["attendees"] == ["Speaker 1"]


@pytest.mark.asyncio
async def test_generate_mom_empty_transcript_returns_blank():
    # Should NOT call the LLM or invent a summary when the transcript is empty.
    called = {"n": 0}

    class Boom:
        async def complete_json(self, *a, **k):
            called["n"] += 1
            return {"summary": "hallucinated"}

    svc = GenerationService(llm=Boom())
    mom = await svc.generate_mom("   ")
    assert mom == GenerationService._empty_mom()
    assert called["n"] == 0
