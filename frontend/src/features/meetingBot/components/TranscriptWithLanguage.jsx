import { useEffect, useRef, useState } from "react";
import { meetingBotApi } from "../services/meetingBotApi.js";
import TranscriptViewer from "./TranscriptViewer.jsx";

// Audio transcript with a language filter. "As spoken" shows the original
// mixed-language transcript; हिंदी / English translate every line into that one
// language (translated once on the server, then cached). Other views fall back
// to the original text on error.
const LANGS = [
  { key: "native", label: "As spoken", hint: "Original language of the meeting" },
  { key: "hi", label: "हिंदी", hint: "Translate everything to Hindi" },
  { key: "en", label: "English", hint: "Translate everything to English" },
];

export default function TranscriptWithLanguage({ meetingId, source, initialChunks }) {
  const [lang, setLang] = useState("native");
  const [chunks, setChunks] = useState(initialChunks || []);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const cache = useRef({ native: initialChunks || [] });

  // Keep the native view in sync if the parent refetches the transcript.
  useEffect(() => {
    cache.current.native = initialChunks || [];
    if (lang === "native") setChunks(initialChunks || []);
  }, [initialChunks]); // eslint-disable-line react-hooks/exhaustive-deps

  async function pick(next) {
    if (next === lang) return;
    setLang(next);
    setError(null);
    if (cache.current[next]) {
      setChunks(cache.current[next]);
      return;
    }
    setLoading(true);
    try {
      const data = await meetingBotApi.getTranscript(meetingId, source, next);
      cache.current[next] = data.chunks || [];
      setChunks(data.chunks || []);
    } catch (e) {
      setError("Could not translate the transcript. Showing as spoken.");
      setLang("native");
      setChunks(cache.current.native);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <div className="mb-lang-filter" role="group" aria-label="Transcript language">
        <span className="mb-lang-filter-label">Language</span>
        {LANGS.map((l) => (
          <button
            key={l.key}
            type="button"
            className={`mb-lang-chip${lang === l.key ? " active" : ""}`}
            onClick={() => pick(l.key)}
            disabled={loading}
            title={l.hint}
          >
            {l.label}
          </button>
        ))}
        {loading && <span className="mb-lang-loading">Translating…</span>}
      </div>
      {error && <p className="warn">{error}</p>}
      <TranscriptViewer chunks={chunks} />
    </div>
  );
}
