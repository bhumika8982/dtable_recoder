"""Optional embeddings for transcript chunks (search / comparison / QA).

Embeddings are created ONLY when explicitly requested and ONLY if a provider is
available. The service is pluggable and degrades gracefully:

  * if ``sentence-transformers`` is installed -> local, free embeddings;
  * else if an OpenAI key with quota is configured -> OpenAI embeddings;
  * else -> no-op (chunks are stored without embeddings).

This keeps the flow production-ready without hard-requiring a paid provider.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

_st_model = None  # cached sentence-transformers model


def _provider() -> str:
    import importlib.util as u

    if u.find_spec("sentence_transformers"):
        return "sentence_transformers"
    from app.config import settings

    if settings.openai_api_key:
        return "openai"
    return "none"


def provider_available() -> bool:
    return _provider() != "none"


async def embed_query(text: str) -> Optional[list[float]]:
    """Embed a single query string (same provider as chunks)."""
    provider = _provider()
    if provider == "none" or not text.strip():
        return None
    try:
        vecs = await _embed_texts([text], provider)
        return vecs[0] if vecs else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Query embedding failed: %s", exc)
        return None


async def embed_chunks(chunks: list[dict]) -> int:
    """Attach an ``embedding`` vector to each chunk in place. Returns count done.

    Best-effort: any failure leaves chunks intact (without embeddings).
    """
    provider = _provider()
    if provider == "none" or not chunks:
        logger.info("Embeddings skipped (no provider / no chunks).")
        return 0
    try:
        vectors = await _embed_texts([c["text"] for c in chunks], provider)
    except Exception as exc:  # noqa: BLE001 — embeddings are optional
        logger.warning("Embedding generation failed (continuing without): %s", exc)
        return 0
    done = 0
    for chunk, vec in zip(chunks, vectors):
        if vec is not None:
            chunk["embedding"] = vec
            chunk["embedding_id"] = chunk.get("chunk_id")
            done += 1
    logger.info("Embeddings created for %d chunks via %s.", done, provider)
    return done


async def _embed_texts(texts: list[str], provider: str) -> list[Optional[list[float]]]:
    if provider == "sentence_transformers":
        import asyncio

        global _st_model
        if _st_model is None:
            from sentence_transformers import SentenceTransformer

            from app.config import settings

            _st_model = SentenceTransformer(settings.embedding_model_name)
        loop = asyncio.get_running_loop()
        vecs = await loop.run_in_executor(
            None, lambda: _st_model.encode(texts, normalize_embeddings=True).tolist()
        )
        return vecs

    # OpenAI fallback.
    from openai import AsyncOpenAI

    from app.config import settings

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    resp = await client.embeddings.create(
        model=settings.openai_embedding_model, input=texts
    )
    return [d.embedding for d in resp.data]
