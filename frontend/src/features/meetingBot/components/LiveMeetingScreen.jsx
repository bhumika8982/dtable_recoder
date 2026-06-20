import { useEffect, useRef, useState } from "react";
import { meetingBotApi } from "../services/meetingBotApi.js";
import StatusBadge from "./StatusBadge.jsx";
import TranscriptViewer from "./TranscriptViewer.jsx";

// Live meeting view: bot/recording statuses + real-time transcript via SSE.
export default function LiveMeetingScreen({ meeting, onUpdate }) {
  const id = meeting.meeting_id;
  const [chunks, setChunks] = useState([]);
  const seen = useRef(new Set());

  // Subscribe to the SSE stream for live transcript + status updates.
  useEffect(() => {
    const es = new EventSource(meetingBotApi.eventsUrl(id));
    es.onmessage = (e) => {
      let msg;
      try {
        msg = JSON.parse(e.data);
      } catch (_) {
        return;
      }
      if (msg.type === "transcript") {
        const d = msg.data;
        const key = `${d.start_time}:${d.text}`;
        if (!seen.current.has(key)) {
          seen.current.add(key);
          setChunks((prev) => [...prev, d]);
        }
      } else if (msg.type === "status" || msg.type === "meeting_completed") {
        onUpdate?.(); // re-fetch meeting detail
      }
    };
    es.onerror = () => {}; // browser auto-reconnects
    return () => es.close();
  }, [id]);

  return (
    <div>
      <div className="mb-status-grid">
        <StatusBadge label="Bot" status={meeting.bot_status} />
        <StatusBadge label="Live transcript" status={meeting.live_transcript_status} />
        <StatusBadge label="Audio" status={meeting.audio_recording_status} />
        <StatusBadge label="Video" status={meeting.video_recording_status} />
      </div>

      <h3>Live Transcript</h3>
      <TranscriptViewer
        chunks={chunks}
        emptyText="Waiting for the bot to join and start speaking…"
      />
      <p className="muted" style={{ marginTop: 12 }}>
        Live transcript needs Recall to reach this server. In local dev, set
        <code> MEETING_BOT_WEBHOOK_BASE_URL </code> to an ngrok URL. Audio &amp;
        video are recorded regardless and available after the meeting.
      </p>
    </div>
  );
}
