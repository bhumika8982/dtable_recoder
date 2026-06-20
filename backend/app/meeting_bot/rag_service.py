"""Embeddings + retrieval-augmented Q&A over a meeting's transcripts.

Flow:
  * ``generate_embeddings`` embeds every transcript chunk (live/audio/video that
    exists) with a free local model and stores the vectors on the chunks.
  * ``ask`` embeds the question, ranks chunks by cosine similarity, and asks the
    LLM (Groq) to answer grounded only in the retrieved chunks, returning the
    answer plus its source lines.

Single-meeting scale (a few hundred chunks), so similarity is computed in-process
with numpy — no external vector DB needed.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.meeting_bot import embedding_service
from app.meeting_bot.live_events import broker
from app.meeting_bot.models import MomStatus, Source, TranscriptStatus
from app.meeting_bot.repository import MeetingBotRepository
from app.meeting_bot.utils import fmt_timestamp, new_correlation_id
from app.services.llm_service import LLMService

logger = logging.getLogger(__name__)

_ALL_SOURCES = (Source.LIVE, Source.AUDIO, Source.VIDEO)

_ASK_SYSTEM = (
    "You are a smart meeting assistant answering questions about ONE meeting, "
    "using ONLY the provided transcript excerpts.\n"
    "- The user's question may have typos, casual phrasing, or be in English or "
    "Hindi (Devanagari or romanized) — infer their true intent generously, like "
    "ChatGPT/Gemini would, and answer the underlying need.\n"
    "- The transcript may mix English and Hindi. Understand both. Answer in the "
    "same language the user asked in (default English).\n"
    "- Be concise, specific and helpful. Quote names, decisions, action items, "
    "numbers and timestamps when relevant.\n"
    "- If the excerpts truly don't contain the answer, say you couldn't find it "
    "in this meeting's transcript — do NOT invent facts."
)


# --------------------------------------------------------------------------- #
# Embedding generation (user-triggered)
# --------------------------------------------------------------------------- #
async def generate_embeddings(meeting_id: str, db) -> None:
    repo = MeetingBotRepository(db)
    cid = new_correlation_id()
    if not embedding_service.provider_available():
        await repo.update_meeting(meeting_id, {
            "embeddings_status": TranscriptStatus.FAILED.value,
            "embeddings_error": "No embedding provider available.",
        })
        return

    await repo.update_meeting(meeting_id, {"embeddings_status": TranscriptStatus.GENERATING.value})
    await broker.publish(meeting_id, "status", {"embeddings_status": "generating"})
    total = 0
    try:
        for source in _ALL_SOURCES:
            chunks = await repo.get_chunks(meeting_id, source.value, limit=100000)
            if not chunks:
                continue
            done = await embedding_service.embed_chunks(chunks)
            if done:
                await repo.save_chunk_embeddings(meeting_id, source.value, chunks)
                total += done
        await repo.update_meeting(meeting_id, {
            "embeddings_status": TranscriptStatus.GENERATED.value,
            "embedded_chunks": total,
        })
        await broker.publish(meeting_id, "status", {"embeddings_status": "generated"})
        logger.info("[%s] embeddings generated for %d chunks", cid, total)
    except Exception as exc:  # noqa: BLE001
        logger.exception("[%s] embedding generation failed", cid)
        await repo.update_meeting(meeting_id, {
            "embeddings_status": TranscriptStatus.FAILED.value,
            "embeddings_error": str(exc) or type(exc).__name__,
        })
        await broker.publish(meeting_id, "status", {"embeddings_status": "failed"})


# --------------------------------------------------------------------------- #
# Ask (retrieval-augmented)
# --------------------------------------------------------------------------- #
async def ask(meeting_id: str, question: str, db, top_k: int = 8) -> dict[str, Any]:
    repo = MeetingBotRepository(db)
    chunks = await repo.get_embedded_chunks(meeting_id)
    if not chunks:
        return {
            "answer": "No embeddings yet. Click \"Generate Embeddings\" first so I can "
                      "search the transcript.",
            "sources": [],
        }
    qvec = await embedding_service.embed_query(question)
    if qvec is None:
        return {"answer": "Embedding model unavailable.", "sources": []}

    ranked = _rank(qvec, chunks)[:top_k]
    context = "\n".join(
        f"[{fmt_timestamp(c.get('start_time'))}] {c.get('speaker_name') or 'Unknown'}: {c.get('text')}"
        for c, _ in ranked
    )
    user = f"Transcript excerpts:\n{context}\n\nQuestion: {question}\nAnswer:"
    try:
        answer = await LLMService().complete_text(_ASK_SYSTEM, user)
    except Exception as exc:  # noqa: BLE001
        logger.exception("ask LLM call failed")
        answer = f"Could not generate an answer ({type(exc).__name__})."
    sources = [
        {
            "source": c.get("source"),
            "speaker_name": c.get("speaker_name") or "Unknown",
            "start_time": c.get("start_time"),
            "text": c.get("text"),
            "score": round(float(score), 3),
        }
        for c, score in ranked
    ]
    return {"answer": answer, "sources": sources}


def _rank(qvec: list[float], chunks: list[dict]) -> list[tuple[dict, float]]:
    import numpy as np

    q = np.asarray(qvec, dtype="float32")
    qn = q / (np.linalg.norm(q) + 1e-9)
    scored: list[tuple[dict, float]] = []
    for c in chunks:
        emb = c.get("embedding")
        if not emb:
            continue
        v = np.asarray(emb, dtype="float32")
        sim = float(np.dot(qn, v / (np.linalg.norm(v) + 1e-9)))
        scored.append((c, sim))
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored
