import { useEffect, useState } from "react";
import { meetingBotApi } from "../services/meetingBotApi.js";
import StatusBadge from "./StatusBadge.jsx";
import RecordingPlayer from "./RecordingPlayer.jsx";
import TranscriptWithLanguage from "./TranscriptWithLanguage.jsx";
import MomViewer from "./MomViewer.jsx";

// ── tiny shared helpers ───────────────────────────────────────────────────────

function SectionCard({ icon, title, badge, children }) {
  return (
    <div className="card vp-card">
      <div className="vp-card-head">
        <span className="vp-card-icon">{icon}</span>
        <h3>{title}</h3>
        {badge !== undefined && <StatusBadge status={badge} />}
      </div>
      <div className="vp-card-body">{children}</div>
    </div>
  );
}

function EmptyHint({ text, sub }) {
  return (
    <div className="vp-empty">
      <p className="vp-empty-text">{text}</p>
      {sub && <p className="vp-empty-sub">{sub}</p>}
    </div>
  );
}

function Spinner({ text }) {
  return (
    <div className="vp-spinner-row">
      <span className="vp-spinner" />
      <span className="muted">{text}</span>
    </div>
  );
}

// ── Main combined page ────────────────────────────────────────────────────────

/**
 * Combined page: Video Recording + Video Transcript + MoM
 *
 * Shown when user clicks the "Video" card in the meeting grid.
 * Everything is self-contained — generates transcript and MoM on demand,
 * never auto-triggers anything.
 */
export default function VideoPage({ meeting, onUpdate }) {
  const id = meeting.meeting_id;
  const a = meeting.available_actions || {};

  const txStatus  = meeting.video_transcript_status  || "not_started";
  const momStatus = meeting.video_mom_status          || "not_started";
  const recStatus = meeting.video_recording_status   || "not_started";

  // ── loaded data ──
  const [transcript, setTranscript] = useState(null);
  const [mom,        setMom]        = useState(null);

  // ── local busy flags for instant button feedback ──
  const [txBusy,  setTxBusy]  = useState(false);
  const [momBusy, setMomBusy] = useState(false);

  // ── load transcript when generated ──
  useEffect(() => {
    if (txStatus === "generated") {
      meetingBotApi.getTranscript(id, "video").then(setTranscript).catch(() => null);
    }
  }, [id, txStatus]);

  // ── load MoM when generated ──
  useEffect(() => {
    if (momStatus === "generated") {
      meetingBotApi.getMom(id, "video").then(setMom).catch(() => null);
    }
  }, [id, momStatus]);

  // ── poll while anything is still generating ──
  const generating = txStatus === "generating" || momStatus === "generating";
  useEffect(() => {
    if (!generating) return;
    const t = setInterval(() => onUpdate?.(), 4000);
    return () => clearInterval(t);
  }, [generating]);

  // ── action handlers ──
  async function handleGenerateTranscript() {
    setTxBusy(true);
    try {
      await meetingBotApi.transcribeVideo(id);
      onUpdate?.();
    } catch (e) {
      alert(`Video transcription failed: ${e.message}`);
    } finally {
      setTxBusy(false);
    }
  }

  async function handleGenerateMom() {
    setMomBusy(true);
    try {
      await meetingBotApi.generateVideoMom(id);
      onUpdate?.();
    } catch (e) {
      alert(`MoM generation failed: ${e.message}`);
    } finally {
      setMomBusy(false);
    }
  }

  const txGenerated  = txStatus  === "generated";
  const txGenerating = txStatus  === "generating" || txBusy;
  const txFailed     = txStatus  === "failed";

  const momGenerated  = momStatus === "generated";
  const momGenerating = momStatus === "generating" || momBusy;
  const momFailed     = momStatus === "failed";

  const canGenTx  = a.can_generate_video_transcript && !txBusy;
  const canGenMom = a.can_generate_video_mom        && !momBusy;

  return (
    <div className="vp-root">

      {/* ── Section 1: Recording ──────────────────────────────────────────── */}
      <SectionCard icon="🎬" title="Video Recording" badge={recStatus}>
        <RecordingPlayer
          type="video"
          url={meeting.video_recording_url}
          status={recStatus}
        />
      </SectionCard>

      {/* ── Section 2: Transcript ─────────────────────────────────────────── */}
      <SectionCard icon="📄" title="Video Transcript" badge={txStatus}>
        {txGenerating && (
          <Spinner text="Generating transcript — this may take a few minutes for long recordings…" />
        )}
        {txFailed && (
          <p className="vp-error">
            Transcription failed. Please try again.
          </p>
        )}

        {txGenerated ? (
          <TranscriptWithLanguage
            meetingId={id}
            source="video"
            initialChunks={transcript?.chunks}
          />
        ) : !txGenerating && (
          <div className="vp-action-block">
            <EmptyHint
              text="Transcript not generated yet."
              sub="Click the button below to start transcription. This runs only when you request it."
            />
            <button onClick={handleGenerateTranscript} disabled={!canGenTx}>
              {txBusy ? "Starting…" : "Generate Video Transcript"}
            </button>
          </div>
        )}
      </SectionCard>

      {/* ── Section 3: MoM ───────────────────────────────────────────────── */}
      <SectionCard icon="📋" title="Minutes of Meeting" badge={momStatus}>
        {momGenerating && (
          <Spinner text="Generating Minutes of Meeting…" />
        )}
        {momFailed && (
          <p className="vp-error">MoM generation failed. Please try again.</p>
        )}

        {momGenerated ? (
          <MomViewer mom={mom} />
        ) : !momGenerating && (
          <div className="vp-action-block">
            {!txGenerated ? (
              <EmptyHint
                text="Transcript not generated yet."
                sub="Generate the video transcript first, then you can generate MoM."
              />
            ) : (
              <EmptyHint
                text="MoM not generated yet."
                sub="Click Generate MoM to create minutes from the video transcript."
              />
            )}
            <button onClick={handleGenerateMom} disabled={!canGenMom}>
              {momBusy ? "Starting…" : "Generate MoM"}
            </button>
          </div>
        )}
      </SectionCard>

    </div>
  );
}
