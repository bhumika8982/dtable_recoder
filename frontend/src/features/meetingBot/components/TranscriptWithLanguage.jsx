import { useEffect, useRef, useState } from "react";
import { meetingBotApi } from "../services/meetingBotApi.js";
import TranscriptViewer from "./TranscriptViewer.jsx";

// Language options for the transcript viewer.
// "native" = original spoken language (no translation).
const LANGS = [
  { key: "native", label: "As spoken",  hint: "Original spoken language — preserved exactly as recorded" },
  { key: "hi",     label: "हिंदी",       hint: "Full transcript translated into Hindi (Devanagari)" },
  { key: "en",     label: "English",    hint: "Full transcript translated into English" },
];

// Map WhisperX ISO 639-1 codes to human-readable labels for the badge.
const LANG_LABEL = {
  en: "English",
  hi: "Hindi",
  ur: "Urdu",
  fr: "French",
  de: "German",
  es: "Spanish",
  zh: "Chinese",
  ja: "Japanese",
  ko: "Korean",
  ar: "Arabic",
  pt: "Portuguese",
  ru: "Russian",
  it: "Italian",
};

// Selects the correct translate function based on transcript source.
function getTranslateFn(source) {
  return source === "video"
    ? (meetingId, lang) => meetingBotApi.translateVideoTranscript(meetingId, lang)
    : (meetingId, lang) => meetingBotApi.translateAudioTranscript(meetingId, lang);
}

/**
 * Transcript viewer with language tabs.
 *
 * Props:
 *   meetingId     — meeting ID used for API calls
 *   source        — "audio" | "video"
 *   initialChunks — original (as-spoken) transcript chunks
 *
 * Behaviour:
 *   • "As spoken" always shows initialChunks — no API call needed.
 *   • "हिंदी" / "English" call the dedicated POST translate endpoint on first
 *     click; the result is cached in a useRef so switching back and forth is
 *     instant with no redundant network requests.
 *   • The backend also caches translations in MongoDB, so even after a page
 *     reload the LLM is only called once per language.
 */
export default function TranscriptWithLanguage({ meetingId, source, initialChunks, detectedLanguage }) {
  const [activeLang, setActiveLang] = useState("native");
  const [displayChunks, setDisplayChunks] = useState(initialChunks || []);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // In-component cache: { native: [...], hi: [...], en: [...] }
  // useRef so cache updates never cause extra re-renders.
  const cache = useRef({ native: initialChunks || [] });

  // Keep the native cache in sync whenever the parent re-fetches the transcript.
  useEffect(() => {
    cache.current.native = initialChunks || [];
    if (activeLang === "native") setDisplayChunks(initialChunks || []);
  }, [initialChunks]); // eslint-disable-line react-hooks/exhaustive-deps

  const translateFn = getTranslateFn(source);

  async function pickLang(lang) {
    if (lang === activeLang) return;
    setError(null);

    // "As spoken" — always available from the cache.
    if (lang === "native") {
      setActiveLang("native");
      setDisplayChunks(cache.current.native);
      return;
    }

    // Already translated in this session — show instantly.
    if (cache.current[lang]) {
      setActiveLang(lang);
      setDisplayChunks(cache.current[lang]);
      return;
    }

    // First time selecting this language — call the translate endpoint.
    setActiveLang(lang);   // switch tab immediately for responsive feel
    setLoading(true);
    try {
      const data = await translateFn(meetingId, lang);
      const translated = data.chunks || [];
      cache.current[lang] = translated;
      setDisplayChunks(translated);
    } catch (e) {
      setError(
        "Translation failed — showing original transcript. " +
        "Check that the LLM service is configured correctly."
      );
      // Fall back to "As spoken"
      setActiveLang("native");
      setDisplayChunks(cache.current.native);
    } finally {
      setLoading(false);
    }
  }

  const langLabel = detectedLanguage
    ? LANG_LABEL[detectedLanguage] || detectedLanguage.toUpperCase()
    : null;

  return (
    <div className="txwl">
      {/* Detected language badge — shown only when viewing "As spoken" */}
      {langLabel && activeLang === "native" && (
        <div className="txwl-detected-lang" title="Language auto-detected by WhisperX">
          <span className="txwl-detected-lang-icon">🌐</span>
          Detected: <strong>{langLabel}</strong>
          <span className="txwl-detected-lang-hint"> — transcript preserved in original spoken language</span>
        </div>
      )}

      {/* Language tab bar */}
      <div className="txwl-tabs" role="group" aria-label="Transcript language">
        <span className="txwl-tabs-label">Language</span>
        {LANGS.map((l) => (
          <button
            key={l.key}
            type="button"
            className={`txwl-tab${activeLang === l.key ? " txwl-tab-active" : ""}`}
            onClick={() => pickLang(l.key)}
            disabled={loading}
            title={l.hint}
          >
            {l.label}
            {loading && activeLang === l.key && (
              <span className="txwl-tab-spinner" aria-hidden="true" />
            )}
          </button>
        ))}
      </div>

      {/* Error banner */}
      {error && (
        <div className="txwl-error" role="alert">
          <span className="txwl-error-icon">⚠</span>
          {error}
        </div>
      )}

      {/* Translating overlay hint (shown while the same tab is loading) */}
      {loading && (
        <p className="txwl-translating">
          Translating transcript — this may take a moment for long meetings…
        </p>
      )}

      {/* Transcript */}
      <div className="txwl-body">
        <TranscriptViewer
          chunks={displayChunks}
          emptyText="No transcript available."
        />
      </div>
    </div>
  );
}
