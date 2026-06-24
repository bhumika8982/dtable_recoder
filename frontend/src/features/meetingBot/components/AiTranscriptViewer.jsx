// AI-proofread transcript: shows the FULLY CORRECTED text where words fixed
// by AI are highlighted in red. Hover a red word to see the original ASR output.
function ts(seconds) {
  const s = Math.max(0, Math.round(seconds || 0));
  const hh = String(Math.floor(s / 3600)).padStart(2, "0");
  const mm = String(Math.floor((s % 3600) / 60)).padStart(2, "0");
  const ss = String(s % 60).padStart(2, "0");
  return `${hh}:${mm}:${ss}`;
}

// Render the corrected line, underlining each corrected word/phrase.
function renderLine(correctedText, corrections) {
  if (!corrections || corrections.length === 0) return correctedText;
  let nodes = [correctedText];
  corrections.forEach((c, ci) => {
    if (!c.right) return;
    nodes = nodes.flatMap((node, ni) => {
      if (typeof node !== "string") return [node];
      const idx = node.toLowerCase().indexOf(c.right.toLowerCase());
      if (idx === -1) return [node];
      return [
        node.slice(0, idx),
        <span
          className="mb-corrected"
          key={`${ci}-${ni}-${idx}`}
          title={c.wrong ? `Corrected from: ${c.wrong}` : "Corrected by AI"}
        >
          {node.slice(idx, idx + c.right.length)}
        </span>,
        node.slice(idx + c.right.length),
      ];
    });
  });
  return nodes;
}

export default function AiTranscriptViewer({ chunks }) {
  if (!chunks || chunks.length === 0)
    return <p className="muted">No AI transcript yet.</p>;

  const total = chunks.reduce((n, c) => n + (c.corrections?.length || 0), 0);
  return (
    <div>
      <p className="muted mb-ai-legend">
        AI-corrected transcript — {total} fix{total === 1 ? "" : "es"} (
        <span className="mb-corrected">shown in red</span> — hover to see original).
      </p>
      <div className="mb-transcript">
        {chunks.map((c, i) => (
          <p key={c.chunk_id || i} className="mb-line">
            <span className="ts">[{ts(c.start_time)}]</span>{" "}
            <span className="speaker">{c.speaker_name || "Unknown"}:</span>{" "}
            <span className="utterance">
              {renderLine(c.corrected_text || c.text, c.corrections)}
            </span>
          </p>
        ))}
      </div>
    </div>
  );
}
