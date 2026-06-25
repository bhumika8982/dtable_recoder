"""Thin async wrapper around an OpenAI-compatible client for MOM generation.

Supports two providers (selected via ``LLM_PROVIDER`` in .env):
  * ``openai`` — GPT-4o (paid API).
  * ``groq``   — free-tier, OpenAI-compatible API (Llama 3.3 by default).

Because Groq exposes an OpenAI-compatible endpoint, the same ``AsyncOpenAI``
client works for both — only the ``base_url``, key, and model differ. Provides
JSON-mode chat completions and retries transient errors with backoff.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings

logger = logging.getLogger(__name__)


class LLMService:
    def __init__(self, client: Optional[AsyncOpenAI] = None):
        if client is not None:
            # Injected client (tests / custom wiring) — honour it as-is.
            self._client = client
            self.model = settings.openai_model
        elif settings.llm_provider.lower() == "gemini":
            if not settings.gemini_api_key:
                raise RuntimeError(
                    "LLM_PROVIDER=gemini but GEMINI_API_KEY is not set in .env. "
                    "Get a free key at https://aistudio.google.com/apikey"
                )
            self._client = AsyncOpenAI(
                api_key=settings.gemini_api_key, base_url=settings.gemini_base_url
            )
            self.model = settings.gemini_model
            logger.info("LLM provider: Gemini (model=%s).", self.model)
        elif settings.llm_provider.lower() == "groq":
            if not settings.groq_api_key:
                raise RuntimeError(
                    "LLM_PROVIDER=groq but GROQ_API_KEY is not set in .env. "
                    "Get a free key at https://console.groq.com/keys"
                )
            self._client = AsyncOpenAI(
                api_key=settings.groq_api_key, base_url=settings.groq_base_url
            )
            self.model = settings.groq_model
            logger.info("LLM provider: Groq (model=%s).", self.model)
        else:
            if not settings.openai_api_key:
                raise RuntimeError(
                    "LLM_PROVIDER=openai but OPENAI_API_KEY is not set in .env."
                )
            self._client = AsyncOpenAI(api_key=settings.openai_api_key)
            self.model = settings.openai_model
            logger.info("LLM provider: OpenAI (model=%s).", self.model)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10), reraise=True)
    async def complete_json(
        self, system: str, user: str, temperature: float = 0.2
    ) -> dict[str, Any]:
        """Run a chat completion in JSON mode and parse the result."""
        resp = await self._client.chat.completions.create(
            model=self.model,
            temperature=temperature,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        content = resp.choices[0].message.content or "{}"
        return json.loads(content)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10), reraise=True)
    async def complete_text(
        self, system: str, user: str, temperature: float = 0.3
    ) -> str:
        resp = await self._client.chat.completions.create(
            model=self.model,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content or ""
