// Renders transcript chunks as [HH:MM:SS] Speaker: text lines.
function ts(seconds) {
  const s = Math.max(0, Math.round(seconds || 0));
  const hh = String(Math.floor(s / 3600)).padStart(2, "0");
  const mm = String(Math.floor((s % 3600) / 60)).padStart(2, "0");
  const ss = String(s % 60).padStart(2, "0");
  return `${hh}:${mm}:${ss}`;
}

export default function TranscriptViewer({ chunks, emptyText = "No transcript yet." }) {
  if (!chunks || chunks.length === 0) return <p className="muted">{emptyText}</p>;
  return (
    <div className="mb-transcript">
      {chunks.map((c, i) => (
        <p key={c.chunk_id || i} className="mb-line">
          <span className="ts">[{ts(c.start_time)}]</span>{" "}
          <span className="speaker">{c.speaker_name || "Unknown"}:</span>{" "}
          <span className="utterance">{c.text}</span>
        </p>
      ))}
    </div>
  );
}
