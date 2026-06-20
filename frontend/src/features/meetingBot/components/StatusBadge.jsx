// Small coloured status pill. Maps any status string to a tone.
const TONE = {
  // good
  completed: "ok", generated: "ok", uploaded: "ok", joined: "ok", live: "ok", recording: "ok",
  // working
  joining: "busy", generating: "busy", uploading: "busy", waiting: "busy",
  waiting_for_admit: "busy", recording_status: "busy",
  // bad
  failed: "bad", removed: "bad",
  // idle
  not_started: "idle", created: "idle", not_joined: "idle",
};

export default function StatusBadge({ label, status }) {
  const tone = TONE[status] || "idle";
  return (
    <span className={`mb-badge mb-${tone}`}>
      {label ? `${label}: ` : ""}
      {String(status || "").replace(/_/g, " ")}
    </span>
  );
}
