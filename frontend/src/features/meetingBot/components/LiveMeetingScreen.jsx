import { useEffect, useRef, useState } from "react";
import { meetingBotApi } from "../services/meetingBotApi.js";
import StatusBadge from "./StatusBadge.jsx";
import TranscriptViewer from "./TranscriptViewer.jsx";

// Live meeting view: bot/recording statuses + real-time transcript via SSE.
// Chunks arrive via the SSE stream when Recall can reach this server
// (MEETING_BOT_WEBHOOK_BASE_URL must be a public URL, e.g. an ngrok tunnel).
// Audio + video are always recorded regardless of webhook availability.
export default function LiveMeetingScreen({ meeting, onUpdate }) {
  const id = meeting.meeting_id;
  const [chunks, setChunks] = useState([]);
  const [liveChunkCount, setLiveChunkCount] = useState(0);
  const seen = useRef(new Set());
  const transcriptRef = useRef(null);

  // Subscribe to the SSE stream for live transcript + status updates.
  useEffect(() => {
    const es = new EventSource(meetingBotApi.eventsUrl(id));
    es.onmessage = (e) => {
      let msg;
      try { msg = JSON.parse(e.data); } catch (_) { return; }

      if (msg.type === "transcript") {
        const d = msg.data;
        const key = `${d.start_time}:${d.text}`;
        if (!seen.current.has(key)) {
          seen.current.add(key);
          setChunks((prev) => [...prev, d]);
          setLiveChunkCount((n) => n + 1);
        }
      } else if (msg.type === "status" || msg.type === "meeting_completed") {
        onUpdate?.();
      }
    };
    es.onerror = () => {};
    return () => es.close();
  }, [id]);

  // Auto-scroll to bottom when new chunks arrive.
  useEffect(() => {
    if (transcriptRef.current) {
      transcriptRef.current.scrollTop = transcriptRef.current.scrollHeight;
    }
  }, [chunks]);

  const isLive      = meeting.bot_status === "joined";
  const isRecording = meeting.audio_recording_status === "recording";
  const hasLiveCaption = liveChunkCount > 0;

  return (
    <div className="live-screen">
      {/* Status row */}
      <div className="mb-status-grid">
        <StatusBadge label="Bot" status={meeting.bot_status} />
        <StatusBadge label="Live transcript" status={meeting.live_transcript_status} />
        <StatusBadge label="Audio" status={meeting.audio_recording_status} />
        <StatusBadge label="Video" status={meeting.video_recording_status} />
      </div>

      {/* Recording indicator */}
      {isRecording && (
        <div className="live-recording-bar">
          <span className="live-dot" />
          <strong>Recording in progress</strong>
          <span className="muted"> — audio &amp; video are being captured</span>
        </div>
      )}

      {/* Live Transcript section */}
      <div className="live-tx-section">
        <div className="live-tx-header">
          <h3>Live Transcript</h3>
          {hasLiveCaption && (
            <span className="live-chunk-count muted">{liveChunkCount} segment{liveChunkCount !== 1 ? "s" : ""} captured</span>
          )}
        </div>

        {!hasLiveCaption && (
          <div className="live-tx-notice">
            <div className="live-tx-notice-icon">📡</div>
            <div>
              <p className="live-tx-notice-title">Live captions not streaming yet</p>
              <p className="muted live-tx-notice-body">
                Live captions require Recall to reach this server.
                In local dev, set <code>MEETING_BOT_WEBHOOK_BASE_URL</code> to a public URL
                (e.g. an ngrok tunnel). <strong>Audio &amp; video are always recorded</strong> and
                full transcription is available after the meeting ends.
              </p>
            </div>
          </div>
        )}

        <div className="live-tx-scroll" ref={transcriptRef}>
          <TranscriptViewer
            chunks={chunks}
            emptyText={null}
          />
        </div>
      </div>

      {/* Tip about post-meeting flow */}
      {isLive && (
        <p className="muted live-tip">
          💡 When the meeting ends, the bot will automatically upload recordings.
          Then use the <strong>Audio</strong> or <strong>Video</strong> tabs to generate
          the full transcript and Minutes of Meeting.
        </p>
      )}
    </div>
  );
}
