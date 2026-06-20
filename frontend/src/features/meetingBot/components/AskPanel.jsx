import { useState } from "react";
import { meetingBotApi } from "../services/meetingBotApi.js";
import StatusBadge from "./StatusBadge.jsx";

function ts(seconds) {
  const s = Math.max(0, Math.round(seconds || 0));
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

// "Ask this meeting": generate embeddings, then ask semantic questions over the
// audio/video/live transcripts. Answers are grounded with source lines.
export default function AskPanel({ meeting, onUpdate }) {
  const id = meeting.meeting_id;
  const status = meeting.embeddings_status || "not_started";
  const ready = status === "generated";

  const [busy, setBusy] = useState(false);
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState(null);
  const [asking, setAsking] = useState(false);

  async function makeEmbeddings() {
    setBusy(true);
    try {
      await meetingBotApi.generateEmbeddings(id);
      onUpdate?.();
    } catch (e) {
      alert(`Embeddings failed: ${e.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function submit(e) {
    e.preventDefault();
    if (!question.trim()) return;
    setAsking(true);
    setResult(null);
    try {
      setResult(await meetingBotApi.ask(id, question));
    } catch (err) {
      setResult({ answer: `Error: ${err.message}`, sources: [] });
    } finally {
      setAsking(false);
    }
  }

  return (
    <section className="card">
      <h3>Ask this meeting <StatusBadge label="Embeddings" status={status} /></h3>

      {!ready ? (
        <>
          <p className="muted">
            Generate embeddings to enable semantic search & Q&amp;A over the
            transcript(s).
          </p>
          <button onClick={makeEmbeddings} disabled={busy || status === "generating"}>
            {status === "generating" ? "Generating embeddings…" : busy ? "Starting…" : "Generate Embeddings"}
          </button>
          {meeting.embedded_chunks > 0 && (
            <p className="muted">{meeting.embedded_chunks} chunks embedded.</p>
          )}
        </>
      ) : (
        <>
          <form onSubmit={submit} className="mb-ask-form">
            <input
              placeholder="e.g. What did Bhumika decide? What are the action items?"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
            />
            <button disabled={asking}>{asking ? "Thinking…" : "Ask"}</button>
          </form>
          <p className="muted">{meeting.embedded_chunks} chunks embedded · ask anything about the meeting.</p>

          {result && (
            <div className="mb-answer">
              <p><strong>Answer:</strong> {result.answer}</p>
              {result.sources && result.sources.length > 0 && (
                <details>
                  <summary>Sources ({result.sources.length})</summary>
                  <ul>
                    {result.sources.map((s, i) => (
                      <li key={i}>
                        <span className="ts">[{ts(s.start_time)}]</span>{" "}
                        <span className="speaker">{s.speaker_name}</span> ({s.source}): {s.text}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
          )}
        </>
      )}
    </section>
  );
}
