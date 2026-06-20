// Audio / video player with graceful empty state.
import StatusBadge from "./StatusBadge.jsx";

export default function RecordingPlayer({ type, url, status }) {
  const isVideo = type === "video";
  return (
    <div className="mb-recording">
      <div className="mb-recording-head">
        <strong>{isVideo ? "Video" : "Audio"} Recording</strong>
        <StatusBadge status={status} />
      </div>
      {url ? (
        isVideo ? (
          <video controls src={url} style={{ width: "100%", borderRadius: 8 }} />
        ) : (
          <audio controls src={url} style={{ width: "100%" }} />
        )
      ) : (
        <p className="muted">Not available yet.</p>
      )}
    </div>
  );
}
