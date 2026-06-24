"""AI-proofread transcript.

Takes the (ASR) audio transcript and uses the LLM to find likely transcription
ERRORS — wrong/garbled/homophone words — and predict the correct word from
context. Produces an "ai" transcript where each line keeps the ORIGINAL text
plus a list of corrections ``[{wrong, right}]`` so the UI can underline the
wrong words and show the AI's prediction.

Never rephrases correct content; only fixes clear ASR mistakes. Works for
English and Hindi.
"""
from __future__ import annotations

import logging
import re
import string
import uuid

from app.meeting_bot.live_events import broker
from app.meeting_bot.models import Source, TranscriptStatus
from app.meeting_bot.repository import MeetingBotRepository
from app.meeting_bot.utils import new_correlation_id
from app.services.llm_service import LLMService

logger = logging.getLogger(__name__)

_SYSTEM = (
    "You are an expert transcript proofreader for multilingual speech-recognition "
    "output that may contain English, Hindi (Devanagari), or Hinglish (romanized "
    "Hindi written in Latin letters, e.g. 'Mujhe meeting ke points chahiye'). "
    "Fix recognition errors using context. Fix ALL of:\n"
    "1. Wrong / mis-heard / homophone words (e.g. 'diskuss'->'discuss', "
    "'traning'->'training', 'lunch'->'launch' when the topic is a product launch).\n"
    "2. Garbled non-words.\n"
    "3. ASR REPETITION LOOPS — a word/phrase repeated many times in a row "
    "(e.g. 'अग अग अग अग', 'afafafaf', 'how are you how are you how are you') — "
    "collapse the whole run to its single intended occurrence (wrong = the entire "
    "repeated run exactly as it appears, right = the single intended text).\n\n"
    "CRITICAL LANGUAGE PRESERVATION RULES — never break these:\n"
    "- NEVER translate. Do NOT turn English into Hindi, Hindi into English, or "
    "Hinglish into either pure Hindi or pure English.\n"
    "- NEVER transliterate or change the script. Romanized/Hinglish text stays "
    "in Latin letters; Devanagari stays Devanagari. Do NOT convert 'training' to "
    "'प्रशिक्षण', and do NOT convert romanized Hindi to Devanagari.\n"
    "- PRESERVE Hinglish exactly. If the speaker said 'Mujhe aaj ki meeting ke "
    "points chahiye', keep it romanized — do NOT convert to Devanagari and do NOT "
    "translate to 'I need today's meeting points'.\n"
    "- Do NOT 'purify' Hindi or make it more formal. Keep the casual spoken "
    "wording and the EXACT mix of languages the speaker used. A speaker who mixes "
    "Hindi and English mid-sentence must remain mixed in the same ratio.\n"
    "- Each correction's 'right' value MUST be in the SAME language and script as "
    "the 'wrong' word it replaces.\n"
    "- Leave already-correct words untouched.\n"
    "Return ONLY valid JSON."
)

_USER = """Below are transcript lines as "index: text".
Return JSON exactly as:
{{"corrections": [{{"line": <index int>, "wrong": "<exact word/phrase from that line>", "right": "<corrected word/phrase>"}}]}}
Only include genuine errors. If a line is fine, omit it. Keep "wrong" an exact
substring of that line so it can be located.

LINES:
{lines}"""


async def generate_ai_transcript(meeting_id: str, db) -> None:
    repo = MeetingBotRepository(db)
    cid = new_correlation_id()
    meeting = await repo.get_meeting(meeting_id)
    if not meeting:
        return

    audio_chunks = await repo.get_chunks(meeting_id, Source.AUDIO.value, limit=100000)
    if not audio_chunks:
        await repo.update_meeting(meeting_id, {
            "ai_transcript_status": TranscriptStatus.FAILED.value,
            "ai_transcript_error": "Audio transcript not available yet.",
        })
        return

    await repo.update_meeting(meeting_id, {"ai_transcript_status": TranscriptStatus.GENERATING.value})
    await broker.publish(meeting_id, "status", {"ai_transcript_status": "generating"})
    logger.info("[%s] AI transcript proofread START (%d lines)", cid, len(audio_chunks))

    try:
        numbered = "\n".join(f"{i}: {c.get('text', '')}" for i, c in enumerate(audio_chunks))
        data = await LLMService().complete_json(_SYSTEM, _USER.format(lines=numbered))

        by_line: dict[int, list[dict]] = {}
        for item in data.get("corrections", []) or []:
            ln = item.get("line")
            wrong, right = (item.get("wrong") or "").strip(), (item.get("right") or "").strip()
            if isinstance(ln, int) and wrong and right and wrong.lower() != right.lower():
                by_line.setdefault(ln, []).append({"wrong": wrong, "right": right})

        ai_chunks = []
        total_fixes = 0
        total_repeats = 0
        for i, c in enumerate(audio_chunks):
            original = c.get("text", "")
            corrections = by_line.get(i, [])
            # Keep only corrections whose "wrong" actually appears in the line.
            corrections = [x for x in corrections if x["wrong"].lower() in original.lower()]
            corrected = original
            for x in corrections:
                corrected = _replace_first(corrected, x["wrong"], x["right"])
            # Deterministic final pass: strip elongated garbage + repeated
            # words/phrases so the AI transcript is always clean and readable.
            corrected, repeats = _clean_repetition(corrected)
            total_repeats += repeats
            total_fixes += len(corrections)
            ai_chunks.append({
                "chunk_id": uuid.uuid4().hex,
                "meeting_id": meeting_id,
                "bot_id": c.get("bot_id"),
                "source": Source.AI.value,
                "speaker_name": c.get("speaker_name"),
                "start_time": c.get("start_time"),
                "end_time": c.get("end_time"),
                "text": original,
                "corrected_text": corrected,
                "corrections": corrections,
                "is_final": True,
                "chunk_index": i,
            })

        await repo.replace_chunks(meeting_id, Source.AI.value, ai_chunks)
        full = "\n".join(c["corrected_text"] for c in ai_chunks if c["corrected_text"])
        await repo.update_meeting(meeting_id, {
            "ai_transcript_text": full,
            "ai_transcript_status": TranscriptStatus.GENERATED.value,
            "ai_transcript_fixes": total_fixes,
            "ai_transcript_repeats_removed": total_repeats,
        })
        await broker.publish(meeting_id, "status", {"ai_transcript_status": "generated"})
        logger.info(
            "[%s] AI transcript DONE: %d corrections, %d repeated runs removed",
            cid, total_fixes, total_repeats,
        )
    except Exception as exc:  # noqa: BLE001 — isolated, never breaks other flows
        logger.exception("[%s] AI transcript FAILED", cid)
        await repo.update_meeting(meeting_id, {
            "ai_transcript_status": TranscriptStatus.FAILED.value,
            "ai_transcript_error": str(exc) or type(exc).__name__,
        })
        await broker.publish(meeting_id, "status", {"ai_transcript_status": "failed"})


def _replace_first(text: str, wrong: str, right: str) -> str:
    """Case-insensitive replace of the first occurrence of ``wrong``."""
    idx = text.lower().find(wrong.lower())
    if idx == -1:
        return text
    return text[:idx] + right + text[idx + len(wrong):]


# --- Deterministic repetition cleanup -------------------------------------
# Runs regardless of the LLM so elongated garbage ("aaaaaaaaaaahi") and
# repeated words/phrases ("how are you how are you how are you", "अग अग अग")
# are always removed, leaving a clean, readable AI transcript.

_PUNCT = string.punctuation + "।,.!?।॥"  # incl. Devanagari danda


def _norm(word: str) -> str:
    """Lowercased word without surrounding punctuation (for comparing repeats)."""
    return word.lower().strip(_PUNCT)


def _collapse_char_runs(text: str) -> str:
    """Collapse elongated garbage *inside* a token down to one occurrence.

    Handles two ASR garbage shapes:
    - a single character repeated 4+ times: "aaaaaaaaaaahi" -> "ahi",
      "हहहहहह" -> "ह", "soooooo" -> "so" (threshold 4 keeps "cool"/"hello").
    - a short 2-4 character cycle repeated 3+ times: "bhafafafafafaf" -> "bhaf",
      "तास्च्च्च्च्च्च्" -> "तास्च्", "blahblahblah" -> "blah".
    """
    text = re.sub(r"(\S)\1{3,}", r"\1", text)
    text = re.sub(r"(\S{2,4}?)\1{2,}", r"\1", text)
    return text


def _collapse_phrase_runs(words: list[str], max_size: int = 8) -> tuple[list[str], int]:
    """Collapse immediately-repeated words and phrases to a single copy.

    Handles single words ("you you you" -> "you") and multi-word phrases
    ("how are you how are you" -> "how are you"). Returns the cleaned list and
    how many repeated copies were removed.
    """
    out: list[str] = []
    removed = 0
    i, n = 0, len(words)
    while i < n:
        matched = False
        # Prefer the longest repeated phrase starting here.
        for size in range(min(max_size, (n - i) // 2), 0, -1):
            a = [_norm(w) for w in words[i : i + size]]
            if not any(a):  # all punctuation/empty — skip
                continue
            j = i + size
            # Advance past every consecutive repeat of this phrase.
            while j + size <= n and [_norm(w) for w in words[j : j + size]] == a:
                j += size
            if j > i + size:  # at least one repeat found
                out.extend(words[i : i + size])
                removed += (j - (i + size))
                i = j
                matched = True
                break
        if not matched:
            out.append(words[i])
            i += 1
    return out, removed


def _clean_repetition(text: str) -> tuple[str, int]:
    """Remove ASR repetition garbage. Returns (clean_text, repeats_removed).

    Phrase collapsing runs to a fixpoint so that, e.g., "अग अग अग अग" (which a
    single pass would reduce to the 2-word phrase "अग अग") fully collapses to a
    single "अग".
    """
    if not text or not text.strip():
        return text, 0
    words = _collapse_char_runs(text).split()
    total = 0
    while True:
        words, removed = _collapse_phrase_runs(words)
        total += removed
        if removed == 0:
            break
    return " ".join(words), total
