/**
 * MeetingDashboard — single-page meeting details view.
 *
 * All meeting outputs are visible here without navigating to separate pages:
 *   Row 1  │ Live Transcript        │ MoM
 *   Row 2  │ Video Recording/Transcript/Ask │ Audio Recording/Transcript/Ask
 */
import { useEffect, useRef, useState } from "react";
import { meetingBotApi } from "../services/meetingBotApi.js";
import StatusBadge from "./StatusBadge.jsx";
import TranscriptViewer from "./TranscriptViewer.jsx";
import TranscriptWithLanguage from "./TranscriptWithLanguage.jsx";
import MomViewer from "./MomViewer.jsx";
import RecordingPlayer from "./RecordingPlayer.jsx";

// ── Shared micro-components ───────────────────────────────────────────────────

function DashCard({ icon, title, badge, children, className = "" }) {
  return (
    <div className={`card dash-card ${className}`}>
      <div className="dash-card-head">
        <span className="dash-card-icon">{icon}</span>
        <h3>{title}</h3>
        {badge !== undefined && <StatusBadge status={badge} />}
      </div>
      <div className="dash-card-body">{children}</div>
    </div>
  );
}

function DashSection({ label, children }) {
  return (
    <div className="dash-section">
      {label && <p className="dash-section-label">{label}</p>}
      {children}
    </div>
  );
}

function DashEmpty({ text, hint }) {
  return (
    <div className="dash-empty">
      <p className="dash-empty-text">{text}</p>
      {hint && <p className="dash-empty-hint">{hint}</p>}
    </div>
  );
}

function DashSpinner({ text }) {
  return (
    <div className="dash-spinner-row">
      <span className="dash-spinner" />
      <span className="muted">{text}</span>
    </div>
  );
}

function DashError({ text }) {
  return <p className="dash-error">{text}</p>;
}

// Inline chatbot for per-source Q&A
function AskBot({ meetingId, source, transcriptGenerated, embStatus, onEnableQA, askFn }) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer]     = useState(null);
  const [asking, setAsking]     = useState(false);

  if (!transcriptGenerated) {
    return <DashEmpty text="Generate the transcript first to enable Q&A." />;
  }
  if (embStatus !== "generated") {
    const loading = embStatus === "generating";
    return (
      <div className="dash-ask-setup">
        {loading
          ? <DashSpinner text="Preparing Q&A engine…" />
          : <DashEmpty text="Q&A engine not ready." hint="Click Enable Q&A to set up semantic search." />
        }
        {!loading && (
          <button className="dash-btn-ghost" onClick={onEnableQA}>Enable Q&A</button>
        )}
      </div>
    );
  }

  async function submit(e) {
    e.preventDefault();
    if (!question.trim()) return;
    setAsking(true);
    setAnswer(null);
    try {
      setAnswer(await askFn(meetingId, question));
    } catch (err) {
      setAnswer({ answer: `Error: ${err.message}`, sources: [] });
    } finally {
      setAsking(false);
      setQuestion("");
    }
  }

  return (
    <div className="dash-ask">
      <form className="dash-ask-form" onSubmit={submit}>
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder={`Ask questions from ${source} transcript…`}
          disabled={asking}
        />
        <button type="submit" disabled={asking || !question.trim()}>
          {asking ? "…" : "Ask"}
        </button>
      </form>
      {answer && (
        <div className="dash-answer">
          <p className="dash-answer-text">{answer.answer}</p>
          {answer.sources?.length > 0 && (
            <details>
              <summary>Sources ({answer.sources.length})</summary>
              <ul>
                {answer.sources.map((s, i) => (
                  <li key={i}>
                    <span className="ts">[{fmtTs(s.start_time)}]</span>{" "}
                    <span className="speaker">{s.speaker_name}</span>: {s.text}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
    </div>
  );
}

function fmtTs(s) {
  const v = Math.max(0, Math.round(s || 0));
  return [Math.floor(v / 3600), Math.floor((v % 3600) / 60), v % 60]
    .map((n) => String(n).padStart(2, "0")).join(":");
}

// ── Row 1 Left: Live Transcript ───────────────────────────────────────────────

function LiveTranscriptCard({ meeting, liveTranscript }) {
  const st = meeting.live_transcript_status;
  return (
    <DashCard icon="📝" title="Live Transcript" badge={st}>
      {(!st || st === "not_started") && <DashEmpty text="Live transcript not available yet." />}
      {st === "generating" && <DashSpinner text="Capturing live transcript…" />}
      {st === "failed"     && <DashEmpty text="Live transcript capture failed." />}
      {st === "generated"  && (
        <div className="dash-scroll">
          <TranscriptViewer chunks={liveTranscript?.chunks} emptyText="Live transcript is empty." />
        </div>
      )}
    </DashCard>
  );
}

// ── Row 1 Right: MoM ─────────────────────────────────────────────────────────

function MomCard({ meeting, mom, onGenerate, isBusy }) {
  const a  = meeting.available_actions || {};
  const ls = meeting.live_mom_status;
  const as = meeting.audio_mom_status;

  const isGenerating = ls === "generating" || as === "generating" || isBusy;
  const canGenerate  = !isGenerating && (
    a.can_generate_live_mom ||
    (meeting.audio_transcript_status === "generated" && a.can_generate_audio_mom)
  );

  return (
    <DashCard icon="📋" title="Minutes of Meeting" badge={mom ? "generated" : undefined}>
      {isGenerating && <DashSpinner text="Generating MoM…" />}
      {!isGenerating && !mom && (
        <DashEmpty text="MoM not generated yet." hint="Click Generate MoM to create it." />
      )}
      {!isGenerating && mom && (
        <div className="dash-scroll">
          <MomViewer mom={mom} />
        </div>
      )}
      <div className="dash-card-foot">
        <button onClick={onGenerate} disabled={!canGenerate}>
          {isGenerating ? "Generating…" : "Generate MoM"}
        </button>
      </div>
    </DashCard>
  );
}

// ── Row 2: Media card (Video or Audio) ────────────────────────────────────────

function MediaCard({ type, meeting, transcript, mom, onGenerateTranscript, onGenerateMom,
  isGenTx, isGenMom, onEnableQA }) {
  const isVideo = type === "video";
  const label   = isVideo ? "Video" : "Audio";
  const icon    = isVideo ? "🎬" : "🎵";
  const askFn   = isVideo ? meetingBotApi.askVideo : meetingBotApi.askAudio;
  const a       = meeting.available_actions || {};

  const txStatus  = meeting[`${type}_transcript_status`] || "not_started";
  const momStatus = meeting[`${type}_mom_status`]        || "not_started";
  const embStatus = meeting.embeddings_status            || "not_started";

  const txGenerating  = txStatus  === "generating" || isGenTx;
  const txGenerated   = txStatus  === "generated";
  const txFailed      = txStatus  === "failed";
  const momGenerating = momStatus === "generating" || isGenMom;
  const momGenerated  = momStatus === "generated";

  const canGenTx  = a[`can_generate_${type}_transcript`] && !isGenTx;
  const canGenMom = a[`can_generate_${type}_mom`]        && !isGenMom && !momGenerating;

  return (
    <DashCard icon={icon} title={`${label} Recording`} badge={meeting[`${type}_recording_status`]}>

      {/* Player */}
      <DashSection>
        <RecordingPlayer
          type={type}
          url={meeting[`${type}_recording_url`]}
          status={meeting[`${type}_recording_status`]}
        />
      </DashSection>

      {/* Transcript */}
      <DashSection label={`${label} Transcript`}>
        {txGenerating && <DashSpinner text="Generating transcript…" />}
        {txFailed     && <DashError text="Transcription failed. Please try again." />}
        {!txGenerated && !txGenerating && (
          <>
            <DashEmpty
              text="Transcript not generated yet."
              hint={`Click Generate ${label} Transcript to start.`}
            />
            <button onClick={onGenerateTranscript} disabled={!canGenTx} style={{ marginTop: 10 }}>
              {isGenTx ? "Starting…" : `Generate ${label} Transcript`}
            </button>
          </>
        )}
        {txGenerated && (
          <div className="dash-scroll">
            <TranscriptWithLanguage
              meetingId={meeting.meeting_id}
              source={type}
              initialChunks={transcript?.chunks}
            />
          </div>
        )}
      </DashSection>

      {/* MoM */}
      <DashSection label="Minutes of Meeting">
        {momGenerating && <DashSpinner text="Generating MoM…" />}
        {!momGenerating && !momGenerated && (
          <DashEmpty
            text={txGenerated ? "MoM not generated yet." : `Generate ${label} transcript first.`}
            hint={txGenerated ? "Click Generate MoM." : null}
          />
        )}
        {!momGenerating && momGenerated && (
          <div className="dash-scroll">
            <MomViewer mom={mom} />
          </div>
        )}
        <button
          onClick={onGenerateMom}
          disabled={!canGenMom}
          style={{ marginTop: 10 }}
        >
          {momGenerating ? "Generating…" : "Generate MoM"}
        </button>
      </DashSection>

      {/* Ask */}
      <DashSection label="Ask Questions">
        <AskBot
          meetingId={meeting.meeting_id}
          source={label.toLowerCase()}
          transcriptGenerated={txGenerated}
          embStatus={embStatus}
          onEnableQA={onEnableQA}
          askFn={askFn}
        />
      </DashSection>
    </DashCard>
  );
}

// ── Root export ───────────────────────────────────────────────────────────────

export default function MeetingDashboard({ meeting, onUpdate }) {
  const id = meeting.meeting_id;
  const a  = meeting.available_actions || {};

  // ── data ──────────────────────────────────────────────────────────────────
  const [liveTranscript, setLiveTranscript] = useState(null);
  const [mom,            setMom]            = useState(null);
  const [audioTranscript, setAudioTranscript] = useState(null);
  const [audioMom,        setAudioMom]        = useState(null);
  const [videoTranscript, setVideoTranscript] = useState(null);
  const [videoMom,        setVideoMom]        = useState(null);

  // ── busy flags ────────────────────────────────────────────────────────────
  const [isGeneratingMom,            setIsGeneratingMom]            = useState(false);
  const [isGeneratingAudioTranscript, setIsGeneratingAudioTranscript] = useState(false);
  const [isGeneratingAudioMom,        setIsGeneratingAudioMom]        = useState(false);
  const [isGeneratingVideoTranscript, setIsGeneratingVideoTranscript] = useState(false);
  const [isGeneratingVideoMom,        setIsGeneratingVideoMom]        = useState(false);
  const [embBusy,                     setEmbBusy]                     = useState(false);

  // ── load data when statuses flip ──────────────────────────────────────────
  useEffect(() => {
    if (meeting.live_transcript_status === "generated")
      meetingBotApi.getTranscript(id, "live").then(setLiveTranscript).catch(() => null);
  }, [id, meeting.live_transcript_status]);

  // Page-1 MoM: prefer live, fall back to audio
  useEffect(() => {
    if (meeting.live_mom_status === "generated")
      meetingBotApi.getMom(id, "live").then(setMom).catch(() => null);
    else if (meeting.audio_mom_status === "generated")
      meetingBotApi.getMom(id, "audio").then(setMom).catch(() => null);
    else setMom(null);
  }, [id, meeting.live_mom_status, meeting.audio_mom_status]);

  useEffect(() => {
    if (meeting.audio_transcript_status === "generated")
      meetingBotApi.getTranscript(id, "audio").then(setAudioTranscript).catch(() => null);
  }, [id, meeting.audio_transcript_status]);

  useEffect(() => {
    if (meeting.audio_mom_status === "generated")
      meetingBotApi.getMom(id, "audio").then(setAudioMom).catch(() => null);
  }, [id, meeting.audio_mom_status]);

  useEffect(() => {
    if (meeting.video_transcript_status === "generated")
      meetingBotApi.getTranscript(id, "video").then(setVideoTranscript).catch(() => null);
  }, [id, meeting.video_transcript_status]);

  useEffect(() => {
    if (meeting.video_mom_status === "generated")
      meetingBotApi.getMom(id, "video").then(setVideoMom).catch(() => null);
  }, [id, meeting.video_mom_status]);

  // ── poll while any background job is running ──────────────────────────────
  const anyGenerating =
    meeting.audio_transcript_status === "generating" ||
    meeting.audio_mom_status        === "generating" ||
    meeting.video_transcript_status === "generating" ||
    meeting.video_mom_status        === "generating" ||
    meeting.live_mom_status         === "generating" ||
    meeting.embeddings_status       === "generating";

  useEffect(() => {
    if (!anyGenerating) return;
    const t = setInterval(() => onUpdate?.(), 4000);
    return () => clearInterval(t);
  }, [anyGenerating]);

  // ── action handlers ───────────────────────────────────────────────────────
  async function handleGenerateMom() {
    setIsGeneratingMom(true);
    try {
      if (a.can_generate_live_mom)  await meetingBotApi.generateLiveMom(id);
      else                          await meetingBotApi.generateAudioMom(id);
      onUpdate?.();
    } catch (e) { alert(`MoM generation failed: ${e.message}`); }
    finally     { setIsGeneratingMom(false); }
  }

  async function handleGenerateAudioTranscript() {
    setIsGeneratingAudioTranscript(true);
    try   { await meetingBotApi.transcribeAudio(id); onUpdate?.(); }
    catch (e) { alert(`Audio transcription failed: ${e.message}`); }
    finally   { setIsGeneratingAudioTranscript(false); }
  }

  async function handleGenerateAudioMom() {
    setIsGeneratingAudioMom(true);
    try   { await meetingBotApi.generateAudioMom(id); onUpdate?.(); }
    catch (e) { alert(`Audio MoM failed: ${e.message}`); }
    finally   { setIsGeneratingAudioMom(false); }
  }

  async function handleGenerateVideoTranscript() {
    setIsGeneratingVideoTranscript(true);
    try   { await meetingBotApi.transcribeVideo(id); onUpdate?.(); }
    catch (e) { alert(`Video transcription failed: ${e.message}`); }
    finally   { setIsGeneratingVideoTranscript(false); }
  }

  async function handleGenerateVideoMom() {
    setIsGeneratingVideoMom(true);
    try   { await meetingBotApi.generateVideoMom(id); onUpdate?.(); }
    catch (e) { alert(`Video MoM failed: ${e.message}`); }
    finally   { setIsGeneratingVideoMom(false); }
  }

  async function handleEnableQA() {
    setEmbBusy(true);
    try   { await meetingBotApi.generateEmbeddings(id); onUpdate?.(); }
    catch (e) { alert(`Failed to enable Q&A: ${e.message}`); }
    finally   { setEmbBusy(false); }
  }

  // ── render ────────────────────────────────────────────────────────────────
  return (
    <div className="dash-root">

      {/* Row 1: Live Transcript + MoM */}
      <div className="dash-row">
        <LiveTranscriptCard meeting={meeting} liveTranscript={liveTranscript} />
        <MomCard
          meeting={meeting}
          mom={mom}
          onGenerate={handleGenerateMom}
          isBusy={isGeneratingMom}
        />
      </div>

      {/* Row 2: Video + Audio */}
      <div className="dash-row">
        <MediaCard
          type="video"
          meeting={meeting}
          transcript={videoTranscript}
          mom={videoMom}
          isGenTx={isGeneratingVideoTranscript}
          isGenMom={isGeneratingVideoMom}
          onGenerateTranscript={handleGenerateVideoTranscript}
          onGenerateMom={handleGenerateVideoMom}
          onEnableQA={handleEnableQA}
        />
        <MediaCard
          type="audio"
          meeting={meeting}
          transcript={audioTranscript}
          mom={audioMom}
          isGenTx={isGeneratingAudioTranscript}
          isGenMom={isGeneratingAudioMom}
          onGenerateTranscript={handleGenerateAudioTranscript}
          onGenerateMom={handleGenerateAudioMom}
          onEnableQA={handleEnableQA}
        />
      </div>

    </div>
  );
}
