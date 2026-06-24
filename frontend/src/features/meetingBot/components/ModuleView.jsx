import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { meetingBotApi } from "../services/meetingBotApi.js";
import { MODULE_BY_KEY } from "../modules.js";
import StatusBadge from "./StatusBadge.jsx";
import TranscriptViewer from "./TranscriptViewer.jsx";
import TranscriptWithLanguage from "./TranscriptWithLanguage.jsx";
import AiTranscriptViewer from "./AiTranscriptViewer.jsx";
import MomViewer from "./MomViewer.jsx";
import RecordingPlayer from "./RecordingPlayer.jsx";
import AskPanel from "./AskPanel.jsx";
import VideoPage from "./VideoPage.jsx";

const GENERATING = new Set(["generating", "uploading"]);

// A single module's full page: back button, title + status, then only that
// module's details. Reuses the existing viewers/players and generate buttons —
// design, badges and functionality are unchanged from the combined view.
export default function ModuleView({ meeting, moduleKey, onUpdate }) {
  const id = meeting.meeting_id;
  const navigate = useNavigate();
  const mod = MODULE_BY_KEY[moduleKey];
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);

  const status = mod ? meeting[mod.statusField] : undefined;

  // Load this module's artifact (transcript / MoM) when relevant.
  useEffect(() => {
    const safe = (p) => p.catch(() => null);
    const map = {
      "live-transcript": () => meetingBotApi.getTranscript(id, "live"),
      "audio-transcript": () => meetingBotApi.getTranscript(id, "audio"),
      "ai-transcript": () => meetingBotApi.getTranscript(id, "ai"),
      "video-transcript": () => meetingBotApi.getTranscript(id, "video"),
      "live-mom": () => meetingBotApi.getMom(id, "live"),
      "audio-mom": () => meetingBotApi.getMom(id, "audio"),
      "video-mom": () => meetingBotApi.getMom(id, "video"),
    };
    if (map[moduleKey]) safe(map[moduleKey]()).then(setData);
    else setData(null);
  }, [id, moduleKey, status]);

  // Poll meeting detail while this module is still being generated.
  useEffect(() => {
    if (!GENERATING.has(status)) return;
    const t = setInterval(() => onUpdate?.(), 4000);
    return () => clearInterval(t);
  }, [status]);

  async function trigger(fn, label) {
    setBusy(true);
    try {
      await fn(id);
      onUpdate?.();
    } catch (e) {
      alert(`${label} failed: ${e.message}`);
    } finally {
      setBusy(false);
    }
  }

  if (!mod) {
    return (
      <div>
        <ModuleHeader meeting={meeting} title="Unknown module" status={undefined} onBack={() => navigate(`/meetings/${id}`)} />
        <p className="muted">This module does not exist.</p>
      </div>
    );
  }

  // The combined video page and the ask panel manage their own card layout.
  const noWrapCard = moduleKey === "ask" || moduleKey === "video";

  return (
    <div className="mb-module-page">
      <ModuleHeader
        meeting={meeting}
        title={mod.title}
        status={moduleKey === "video" ? undefined : status}
        onBack={() => navigate(`/meetings/${id}`)}
      />
      {noWrapCard ? (
        renderBody({ moduleKey, meeting, data, status, busy, trigger, onUpdate })
      ) : (
        <section className="card">
          {renderBody({ moduleKey, meeting, data, status, busy, trigger, onUpdate })}
        </section>
      )}
    </div>
  );
}

function ModuleHeader({ meeting, title, status, onBack }) {
  return (
    <div className="mb-module-header">
      <button className="mb-back" onClick={onBack}>← Back</button>
      <div>
        <h2>{title}</h2>
        <p className="muted">{meeting.meeting_title}</p>
      </div>
      {status !== undefined && <StatusBadge status={status} />}
    </div>
  );
}

function renderBody({ moduleKey, meeting, data, status, busy, trigger, onUpdate }) {
  const a = meeting.available_actions || {};
  switch (moduleKey) {
    case "live-transcript":
      return (
        <>
          {meeting.diarization_error && <p className="warn">{meeting.diarization_error}</p>}
          <TranscriptViewer chunks={data?.chunks} emptyText="No live transcript captured." />
        </>
      );

    case "live-mom":
      return <MomViewer mom={data} emptyText="Live MoM not available." />;

    case "audio-recording":
      return (
        <RecordingPlayer type="audio" url={meeting.audio_recording_url} status={meeting.audio_recording_status} />
      );

    case "video-recording":
      return (
        <RecordingPlayer type="video" url={meeting.video_recording_url} status={meeting.video_recording_status} />
      );

    case "audio-transcript":
      return status === "generated" ? (
        <TranscriptWithLanguage meetingId={meeting.meeting_id} source="audio" initialChunks={data?.chunks} detectedLanguage={meeting.audio_transcript_language} />
      ) : (
        <button disabled={!a.can_generate_audio_transcript || busy}
          onClick={() => trigger(meetingBotApi.transcribeAudio, "Audio transcript")}>
          {status === "generating" ? "Generating…" : "Generate Transcript from Audio"}
        </button>
      );

    case "ai-transcript":
      return status === "generated" ? (
        <AiTranscriptViewer chunks={data?.chunks} />
      ) : (
        <>
          {meeting.audio_transcript_status !== "generated" && (
            <p className="muted">Audio transcript will be generated automatically before AI proofreading starts.</p>
          )}
          <button disabled={!a.can_generate_ai_transcript || busy}
            onClick={() => trigger(meetingBotApi.generateAiTranscript, "AI transcript")}>
            {status === "generating" ? "Proofreading…" : "Generate AI Transcript"}
          </button>
        </>
      );

    case "audio-mom":
      return status === "generated" ? (
        <MomViewer mom={data} />
      ) : (
        <>
          {meeting.audio_transcript_status !== "generated" && (
            <p className="muted">
              The meeting transcript is being prepared — the MoM generates from it.
            </p>
          )}
          <button disabled={!a.can_generate_audio_mom || busy}
            onClick={() => trigger(meetingBotApi.generateAudioMom, "MoM")}>
            {status === "generating" ? "Generating MoM…" : "Generate MoM"}
          </button>
        </>
      );

    case "video-transcript":
      return status === "generated" ? (
        <TranscriptWithLanguage
          meetingId={meeting.meeting_id}
          source="video"
          initialChunks={data?.chunks}
          detectedLanguage={meeting.video_transcript_language}
        />
      ) : (
        <button disabled={!a.can_generate_video_transcript || busy}
          onClick={() => trigger(meetingBotApi.transcribeVideo, "Video transcript")}>
          {status === "generating" ? "Generating…" : "Generate Transcript from Video"}
        </button>
      );

    case "video-mom":
      return status === "generated" ? (
        <MomViewer mom={data} />
      ) : (
        <>
          {meeting.video_transcript_status !== "generated" && (
            <p className="muted">Generate the video transcript first.</p>
          )}
          <button disabled={!a.can_generate_video_mom || busy}
            onClick={() => trigger(meetingBotApi.generateVideoMom, "Video MoM")}>
            {status === "generating" ? "Generating…" : "Generate MoM from Video Transcript"}
          </button>
        </>
      );

    case "video":
      return <VideoPage meeting={meeting} onUpdate={onUpdate} />;

    case "ask":
      return <AskPanel meeting={meeting} onUpdate={onUpdate} />;

    default:
      return <p className="muted">Nothing here.</p>;
  }
}
