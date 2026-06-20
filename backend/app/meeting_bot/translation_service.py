"""On-demand transcript translation.

The audio transcript is stored exactly as spoken (mixed Hindi/English/Hinglish).
This service translates every line into a single target language (Hindi or
English) so the UI's language filter can show one consistent language. Results
are cached on the meeting document (keyed by source + language) so each
language is only translated once.
"""
from __future__ import annotations

import logging

from app.meeting_bot.ai_transcript_service import _clean_repetition
from app.meeting_bot.models import Source
from app.meeting_bot.repository import MeetingBotRepository
from app.services.llm_service import LLMService

logger = logging.getLogger(__name__)

# Languages the filter offers (besides the original "as spoken" view).
_LANG_NAMES = {
    "hi": "Hindi, written in Devanagari script (देवनागरी)",
    "en": "English",
}
_NATIVE = {"native", "original", "as-spoken", ""}

_SYSTEM = (
    "You are a professional meeting-transcript translator. Translate each "
    "numbered line FULLY into {language}. Rules:\n"
    "- The ENTIRE line must end up in {language}. Translate ALL words — including "
    "any English or other-language words mixed into the line — so that NO "
    "foreign-language words remain. A mixed Hindi+English line must become a "
    "single clean {language} sentence.\n"
    "- Keep verbatim ONLY: people's names, company/brand names, and short "
    "UPPERCASE acronyms or code identifiers (e.g. WMR, MMR, TPM, API, UI).\n"
    "- Translate the MEANING naturally; do NOT transliterate ordinary words.\n"
    "- If a word or phrase is repeated many times in a row, collapse it to a "
    "single occurrence.\n"
    "- Return exactly one translation per input line, same line numbers.\n"
    "Return ONLY valid JSON."
)

_USER = """Translate these transcript lines into {language}.
Return JSON exactly as:
{{"translations": [{{"line": <index int>, "text": "<translated text>"}}]}}
Translate every line.

LINES:
{lines}"""

_BATCH = 60  # lines per LLM call (keeps each request well within token limits)
_CACHE_VERSION = 3  # bump to invalidate cached translations when the prompt changes


def _src(source) -> str:
    return source.value if isinstance(source, Source) else str(source)


async def translate_transcript(meeting_id: str, source, lang: str, repo: MeetingBotRepository):
    """Return a list of translated texts aligned to the source chunks, or None.

    None means "show the original" (native / unknown language). Results are
    cached on the meeting doc so repeated views are instant.
    """
    lang = (lang or "").lower()
    if lang in _NATIVE or lang not in _LANG_NAMES:
        return None

    src = _src(source)
    chunks = await repo.get_chunks(meeting_id, src, limit=100000)
    if not chunks:
        return []

    meeting = await repo.get_meeting(meeting_id) or {}
    cache = meeting.get(f"{src}_transcript_translations") or {}
    if cache.get("_v") != _CACHE_VERSION:
        cache = {"_v": _CACHE_VERSION}  # stale (old prompt) — drop and re-translate
    cached = cache.get(lang)
    if isinstance(cached, list) and len(cached) == len(chunks):
        return cached  # already translated for this exact transcript

    language = _LANG_NAMES[lang]
    # Strip ASR repetition garbage first so the translated text is clean, and
    # cap absurdly long leftover garbage so it can't blow a batch's token budget.
    texts = [_clean_repetition(c.get("text", ""))[0][:1000] for c in chunks]
    out: list[str] = [""] * len(texts)
    llm = LLMService()

    for start in range(0, len(texts), _BATCH):
        batch = texts[start : start + _BATCH]
        numbered = "\n".join(f"{i}: {t}" for i, t in enumerate(batch))
        try:
            data = await llm.complete_json(
                _SYSTEM.format(language=language),
                _USER.format(language=language, lines=numbered),
            )
            for item in data.get("translations", []) or []:
                ln = item.get("line")
                if isinstance(ln, int) and 0 <= ln < len(batch):
                    out[start + ln] = (item.get("text") or "").strip() or batch[ln]
        except Exception:  # noqa: BLE001 — one bad batch must not drop the rest
            logger.exception("[translate] batch %d failed (lang=%s)", start, lang)

    # Any line the model skipped or that failed falls back to the cleaned text.
    for i, t in enumerate(out):
        if not t:
            out[i] = texts[i]

    cache["_v"] = _CACHE_VERSION
    cache[lang] = out
    await repo.update_meeting(meeting_id, {f"{src}_transcript_translations": cache})
    logger.info("[translate] %s %s -> %s (%d lines)", meeting_id, src, lang, len(out))
    return out
