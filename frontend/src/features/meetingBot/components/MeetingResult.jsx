import { useEffect, useState } from "react";
import { meetingBotApi } from "../services/meetingBotApi.js";
import StatusBadge from "./StatusBadge.jsx";
import TranscriptViewer from "./TranscriptViewer.jsx";
import MomViewer from "./MomViewer.jsx";
import RecordingPlayer from "./RecordingPlayer.jsx";
import AskPanel from "./AskPanel.jsx";

const GENERATING = new Set(["generating", "uploading"]);

// Post-meeting result: live transcript + MoM, recordings, and the optional
// audio/video transcription + MoM flows (only run when the user clicks).
export default function MeetingResult({ meeting, onUpdate }) {
  const id = meeting.meeting_id;
  const a = meeting.available_actions || {};
  const [data, setData] = useState({}); // { liveTr, liveMom, audioTr, audioMom, videoTr, videoMom }
  const [busy, setBusy] = useState(null);

  // Load artifacts that are ready, whenever statuses change.
  useEffect(() => {
    const safe = (p) => p.catch(() => null);
    safe(meetingBotApi.getTranscript(id, "live")).then((t) => upd("liveTr", t));
    if (meeting.live_mom_status === "generated") safe(meetingBotApi.getMom(id, "live")).then((m) => upd("liveMom", m));
    if (meeting.audio_transcript_status === "generated") safe(meetingBotApi.getTranscript(id, "audio")).then((t) => upd("audioTr", t));
    if (meeting.audio_mom_status === "generated") safe(meetingBotApi.getMom(id, "audio")).then((m) => upd("audioMom", m));
    if (meeting.video_transcript_status === "generated") safe(meetingBotApi.getTranscript(id, "video")).then((t) => upd("videoTr", t));
    if (meeting.video_mom_status === "generated") safe(meetingBotApi.getMom(id, "video")).then((m) => upd("videoMom", m));
  }, [
    id, meeting.live_mom_status, meeting.audio_transcript_status,
    meeting.audio_mom_status, meeting.video_transcript_status, meeting.video_mom_status,
  ]);

  // Poll for status while any background job is running.
  useEffect(() => {
    const running = [
      meeting.audio_transcript_status, meeting.audio_mom_status,
      meeting.video_transcript_status, meeting.video_mom_status,
      meeting.audio_recording_status, meeting.video_recording_status,
      meeting.embeddings_status,
    ].some((s) => GENERATING.has(s));
    if (!running) return;
    const t = setInterval(() => onUpdate?.(), 4000);
    return () => clearInterval(t);
  }, [meeting]);

  function upd(key, val) {
    if (val) setData((d) => ({ ...d, [key]: val }));
  }

  async function trigger(fn, label) {
    setBusy(label);
    try {
      await fn(id);
      onUpdate?.();
    } catch (e) {
      alert(`${label} failed: ${e.message}`);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="mb-result">
      <section className="card">
        <h3>Live Transcript <StatusBadge status={meeting.live_transcript_status} /></h3>
        <TranscriptViewer chunks={data.liveTr?.chunks} emptyText="No live transcript captured." />
      </section>

      <section className="card">
        <h3>Live MoM <StatusBadge status={meeting.live_mom_status} /></h3>
        <MomViewer mom={data.liveMom} emptyText="Live MoM not available." />
      </section>

      <section className="card mb-players">
        <RecordingPlayer type="audio" url={meeting.audio_recording_url} status={meeting.audio_recording_status} />
        <RecordingPlayer type="video" url={meeting.video_recording_url} status={meeting.video_recording_status} />
      </section>

      <AskPanel meeting={meeting} onUpdate={onUpdate} />

      {/* ---- Optional: AUDIO ---- */}
      <section className="card">
        <h3>Audio Transcript <StatusBadge status={meeting.audio_transcript_status} /></h3>
        {meeting.audio_transcript_status === "generated" ? (
          <>
            <TranscriptViewer chunks={data.audioTr?.chunks} />
            <h3 style={{ marginTop: 16 }}>Audio MoM <StatusBadge status={meeting.audio_mom_status} /></h3>
            {meeting.audio_mom_status === "generated" ? (
              <MomViewer mom={data.audioMom} />
            ) : (
              <button disabled={!a.can_generate_audio_mom || busy}
                onClick={() => trigger(meetingBotApi.generateAudioMom, "Audio MoM")}>
                {meeting.audio_mom_status === "generating" ? "Generating…" : "Generate MoM from Audio Transcript"}
              </button>
            )}
          </>
        ) : (
          <button disabled={!a.can_generate_audio_transcript || busy}
            onClick={() => trigger(meetingBotApi.transcribeAudio, "Audio transcript")}>
            {meeting.audio_transcript_status === "generating" ? "Generating…" : "Generate Transcript from Audio"}
          </button>
        )}
      </section>

      {/* ---- Optional: VIDEO ---- */}
      <section className="card">
        <h3>Video Transcript <StatusBadge status={meeting.video_transcript_status} /></h3>
        {meeting.video_transcript_status === "generated" ? (
          <>
            <TranscriptViewer chunks={data.videoTr?.chunks} />
            <h3 style={{ marginTop: 16 }}>Video MoM <StatusBadge status={meeting.video_mom_status} /></h3>
            {meeting.video_mom_status === "generated" ? (
              <MomViewer mom={data.videoMom} />
            ) : (
              <button disabled={!a.can_generate_video_mom || busy}
                onClick={() => trigger(meetingBotApi.generateVideoMom, "Video MoM")}>
                {meeting.video_mom_status === "generating" ? "Generating…" : "Generate MoM from Video Transcript"}
              </button>
            )}
          </>
        ) : (
          <button disabled={!a.can_generate_video_transcript || busy}
            onClick={() => trigger(meetingBotApi.transcribeVideo, "Video transcript")}>
            {meeting.video_transcript_status === "generating" ? "Generating…" : "Generate Transcript from Video"}
          </button>
        )}
      </section>
    </div>
  );
}
