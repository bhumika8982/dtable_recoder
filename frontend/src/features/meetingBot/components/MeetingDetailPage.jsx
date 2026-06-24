/**
 * MeetingDetailPage — post-meeting single-page view.
 *
 * Three tabs:
 *   📝 Live Transcript  — Live (left) + AI-corrected (right) + two MoMs below
 *   🎵 Audio            — Player → Transcript → Chat Bot → MoM
 *   🎬 Video            — Player → Transcript → Chat Bot → MoM
 */
import { useEffect, useRef, useState } from "react";
import { meetingBotApi } from "../services/meetingBotApi.js";
import StatusBadge from "./StatusBadge.jsx";
import TranscriptViewer from "./TranscriptViewer.jsx";
import TranscriptWithLanguage from "./TranscriptWithLanguage.jsx";
import AiTranscriptViewer from "./AiTranscriptViewer.jsx";
import MomViewer from "./MomViewer.jsx";
import RecordingPlayer from "./RecordingPlayer.jsx";

// ── helpers ───────────────────────────────────────────────────────────────────

function fmtTs(s) {
  const v = Math.max(0, Math.round(s || 0));
  return [Math.floor(v / 3600), Math.floor((v % 3600) / 60), v % 60]
    .map((n) => String(n).padStart(2, "0")).join(":");
}

function Spin({ sm }) {
  return <span className={`mdp-spin${sm ? " mdp-spin-sm" : ""}`} />;
}

function EmptyBox({ icon = "📭", title, sub }) {
  return (
    <div className="mdp-empty">
      <span className="mdp-empty-icon">{icon}</span>
      <p className="mdp-empty-title">{title}</p>
      {sub && <p className="mdp-empty-sub">{sub}</p>}
    </div>
  );
}

function Panel({ icon, title, badge, accent, children }) {
  return (
    <div className={`mdp-panel${accent ? " mdp-panel-accent" : ""}`}>
      <div className="mdp-panel-head">
        <span className="mdp-panel-icon">{icon}</span>
        <h3>{title}</h3>
        {badge !== undefined && <StatusBadge status={badge} />}
      </div>
      <div className="mdp-panel-body">{children}</div>
    </div>
  );
}

function SectionLabel({ children }) {
  return <p className="mdp-sec-label">{children}</p>;
}

// ── Tab: Live Transcript ──────────────────────────────────────────────────────

function LiveTab({ meeting, onUpdate }) {
  const id = meeting.meeting_id;
  const a  = meeting.available_actions || {};

  const [liveTx,   setLiveTx]   = useState(null);
  const [aiTx,     setAiTx]     = useState(null);
  const [liveMom,  setLiveMom]  = useState(null);
  const [audioMom, setAudioMom] = useState(null);

  const [aiTxBusy,  setAiTxBusy]  = useState(false);
  const [liveMomBusy, setLiveMomBusy] = useState(false);
  const [audioMomBusy, setAudioMomBusy] = useState(false);

  useEffect(() => {
    if (meeting.live_transcript_status === "generated")
      meetingBotApi.getTranscript(id, "live").then(setLiveTx).catch(() => null);
  }, [id, meeting.live_transcript_status]);

  useEffect(() => {
    if (meeting.ai_transcript_status === "generated")
      meetingBotApi.getTranscript(id, "ai").then(setAiTx).catch(() => null);
  }, [id, meeting.ai_transcript_status]);

  useEffect(() => {
    if (meeting.live_mom_status === "generated")
      meetingBotApi.getMom(id, "live").then(setLiveMom).catch(() => null);
  }, [id, meeting.live_mom_status]);

  useEffect(() => {
    if (meeting.audio_mom_status === "generated")
      meetingBotApi.getMom(id, "audio").then(setAudioMom).catch(() => null);
  }, [id, meeting.audio_mom_status]);

  const generating =
    meeting.ai_transcript_status === "generating" ||
    meeting.live_mom_status === "generating" ||
    meeting.audio_mom_status === "generating";

  useEffect(() => {
    if (!generating) return;
    const t = setInterval(() => onUpdate?.(), 4000);
    return () => clearInterval(t);
  }, [generating]);

  async function handleGenAi() {
    setAiTxBusy(true);
    try { await meetingBotApi.generateAiTranscript(id); onUpdate?.(); }
    catch (e) { alert(`AI transcript failed: ${e.message}`); }
    finally { setAiTxBusy(false); }
  }

  async function handleGenLiveMom() {
    setLiveMomBusy(true);
    try { await meetingBotApi.generateLiveMom(id); onUpdate?.(); }
    catch (e) { alert(`MoM failed: ${e.message}`); }
    finally { setLiveMomBusy(false); }
  }

  async function handleGenAudioMom() {
    setAudioMomBusy(true);
    try { await meetingBotApi.generateAudioMom(id); onUpdate?.(); }
    catch (e) { alert(`MoM failed: ${e.message}`); }
    finally { setAudioMomBusy(false); }
  }

  const liveStatus = meeting.live_transcript_status;
  const aiStatus   = meeting.ai_transcript_status;
  const lmStatus   = meeting.live_mom_status;
  const amStatus   = meeting.audio_mom_status;

  const canGenAi  = a.can_generate_ai_transcript && !aiTxBusy;
  const canLiveMom  = a.can_generate_live_mom && !liveMomBusy;
  const canAudioMom = a.can_generate_audio_mom && !audioMomBusy;

  return (
    <div className="mdp-live-tab">
      {/* ── Row 1: transcripts side by side ── */}
      <div className="mdp-row">

        {/* Left — Live Transcript */}
        <Panel icon="📝" title="Live Transcript" badge={liveStatus}>
          {(!liveStatus || liveStatus === "not_started") && (
            <EmptyBox icon="⏳" title="Live transcript not available yet."
              sub="Live captions are captured while the meeting is running." />
          )}
          {liveStatus === "generating" && (
            <div className="mdp-loading-row"><Spin />Capturing…</div>
          )}
          {liveStatus === "failed" && (
            <EmptyBox icon="⚠️" title="Live transcript capture failed." />
          )}
          {liveStatus === "generated" && (
            <div className="mdp-scroll">
              <TranscriptViewer chunks={liveTx?.chunks}
                emptyText="Live transcript is empty." />
            </div>
          )}
        </Panel>

        {/* Right — AI Transcript */}
        <Panel icon="🤖" title="AI Transcript" badge={aiStatus} accent>
          <p className="mdp-ai-hint">
            AI analyses the live transcript and corrects wrong words.{" "}
            <span className="mdp-ai-correction-sample">Corrected words</span>{" "}
            are shown underlined in blue.
          </p>

          {(aiStatus === "not_started" || !aiStatus) && (
            <div className="mdp-gen-block">
              {meeting.audio_transcript_status !== "generated" && (
                <EmptyBox icon="🎙️" title="Audio transcript not generated yet."
                  sub="Clicking Generate AI Transcript will automatically create the audio transcript first, then run AI proofreading." />
              )}
              <button onClick={handleGenAi} disabled={!canGenAi}>
                {aiTxBusy ? <><Spin sm />Starting…</> : "✨ Generate AI Transcript"}
              </button>
            </div>
          )}
          {aiStatus === "generating" && (
            <div className="mdp-loading-row"><Spin />AI is proofreading the transcript…</div>
          )}
          {aiStatus === "failed" && (
            <div className="mdp-gen-block">
              <EmptyBox icon="⚠️" title="AI transcript generation failed." />
              <button onClick={handleGenAi} disabled={!canGenAi}>Retry</button>
            </div>
          )}
          {aiStatus === "generated" && (
            <div className="mdp-scroll">
              <AiTranscriptViewer chunks={aiTx?.chunks} />
            </div>
          )}
        </Panel>
      </div>

      {/* ── Row 2: MoMs side by side ── */}
      <div className="mdp-row">

        {/* Left — Live MoM */}
        <Panel icon="📋" title="Minutes of Meeting" badge={lmStatus}>
          {lmStatus === "generating" && (
            <div className="mdp-loading-row"><Spin />Generating MoM…</div>
          )}
          {lmStatus === "generated" && liveMom ? (
            <div className="mdp-scroll">
              <MomViewer mom={liveMom} />
            </div>
          ) : lmStatus !== "generating" && (
            <EmptyBox icon="📋" title="MoM not generated yet."
              sub="Click Generate MoM to create minutes from the live transcript." />
          )}
          <div className="mdp-panel-foot">
            <button onClick={handleGenLiveMom} disabled={!canLiveMom}>
              {lmStatus === "generating" ? <><Spin sm />Generating…</> : "Generate MoM"}
            </button>
          </div>
        </Panel>

        {/* Right — AI / Audio MoM */}
        <Panel icon="✨" title="MoM from AI Transcript" badge={amStatus} accent>
          {amStatus === "generating" && (
            <div className="mdp-loading-row"><Spin />Generating MoM…</div>
          )}
          {amStatus === "generated" && audioMom ? (
            <div className="mdp-scroll">
              <MomViewer mom={audioMom} />
            </div>
          ) : amStatus !== "generating" && (
            <EmptyBox icon="✨" title="AI-powered MoM not generated yet."
              sub="Click Generate MoM — audio transcript will be created automatically if not done yet." />
          )}
          <div className="mdp-panel-foot">
            <button onClick={handleGenAudioMom} disabled={!canAudioMom}>
              {amStatus === "generating" ? <><Spin sm />Generating…</> : "Generate MoM"}
            </button>
          </div>
        </Panel>
      </div>
    </div>
  );
}

// ── Chat bot (reusable for audio & video) ─────────────────────────────────────

function ChatBot({ meetingId, source, transcriptGenerated, embStatus, onEnableQA }) {
  const askFn = source === "video" ? meetingBotApi.askVideo : meetingBotApi.askAudio;
  const [messages, setMessages] = useState([]);
  const [input,    setInput]    = useState("");
  const [asking,   setAsking]   = useState(false);
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  if (!transcriptGenerated) {
    return (
      <EmptyBox icon="💬" title="Q&A not available yet."
        sub="Generate the transcript above to enable the chat bot." />
    );
  }

  if (embStatus !== "generated") {
    return (
      <div className="mdp-emb-prompt">
        {embStatus === "generating" ? (
          <div className="mdp-loading-row"><Spin />Preparing Q&amp;A engine…</div>
        ) : (
          <>
            <EmptyBox icon="🔍" title="Q&A engine not ready."
              sub="Enable semantic search to start asking questions about this recording." />
            <button className="mdp-btn-enable-qa" onClick={onEnableQA}>
              🚀 Enable Q&amp;A
            </button>
          </>
        )}
      </div>
    );
  }

  async function send(e) {
    e.preventDefault();
    if (!input.trim() || asking) return;
    const q = input.trim();
    setInput("");
    setMessages((m) => [...m, { role: "user", text: q }]);
    setAsking(true);
    try {
      const res = await askFn(meetingId, q);
      setMessages((m) => [...m, { role: "bot", text: res.answer, sources: res.sources }]);
    } catch (err) {
      setMessages((m) => [...m, { role: "bot", text: `Error: ${err.message}`, sources: [] }]);
    } finally {
      setAsking(false);
    }
  }

  return (
    <div className="mdp-chat">
      <div className="mdp-chat-history">
        {messages.length === 0 && (
          <p className="mdp-chat-hint">
            💡 Ask anything — action items, decisions, who said what, follow-ups…
          </p>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`mdp-msg mdp-msg-${m.role}`}>
            <div className="mdp-msg-bubble">{m.text}</div>
            {m.role === "bot" && m.sources?.length > 0 && (
              <details className="mdp-sources">
                <summary>Sources ({m.sources.length})</summary>
                <ul>
                  {m.sources.map((s, j) => (
                    <li key={j}>
                      <span className="ts">[{fmtTs(s.start_time)}]</span>{" "}
                      <span className="speaker">{s.speaker_name}</span>: {s.text}
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        ))}
        {asking && (
          <div className="mdp-msg mdp-msg-bot">
            <div className="mdp-msg-bubble mdp-msg-thinking">
              <Spin sm /> Thinking…
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>
      <form className="mdp-chat-input-row" onSubmit={send}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={`Ask about the ${source} recording…`}
          disabled={asking}
        />
        <button type="submit" disabled={asking || !input.trim()}>
          Send →
        </button>
      </form>
    </div>
  );
}

// ── Tab: Audio / Video (shared MediaTab) ─────────────────────────────────────

function MediaTab({ type, meeting, onUpdate }) {
  const isVideo = type === "video";
  const id      = meeting.meeting_id;
  const a       = meeting.available_actions || {};
  const label   = isVideo ? "Video" : "Audio";

  const txStatus  = meeting[`${type}_transcript_status`] || "not_started";
  const momStatus = meeting[`${type}_mom_status`]        || "not_started";
  const embStatus = meeting.embeddings_status            || "not_started";

  const [transcript, setTranscript] = useState(null);
  const [mom,        setMom]        = useState(null);
  const [txBusy,     setTxBusy]     = useState(false);
  const [momBusy,    setMomBusy]    = useState(false);
  const [embBusy,    setEmbBusy]    = useState(false);

  useEffect(() => {
    if (txStatus === "generated")
      meetingBotApi.getTranscript(id, type).then(setTranscript).catch(() => null);
  }, [id, txStatus]);

  useEffect(() => {
    if (momStatus === "generated")
      meetingBotApi.getMom(id, type).then(setMom).catch(() => null);
  }, [id, momStatus]);

  const generating = txStatus === "generating" || momStatus === "generating"
    || embStatus === "generating";

  useEffect(() => {
    if (!generating) return;
    const t = setInterval(() => onUpdate?.(), 4000);
    return () => clearInterval(t);
  }, [generating]);

  async function handleGenTranscript() {
    setTxBusy(true);
    try {
      await (isVideo ? meetingBotApi.transcribeVideo : meetingBotApi.transcribeAudio)(id);
      onUpdate?.();
    } catch (e) { alert(`Transcription failed: ${e.message}`); }
    finally { setTxBusy(false); }
  }

  async function handleGenMom() {
    setMomBusy(true);
    try {
      await (isVideo ? meetingBotApi.generateVideoMom : meetingBotApi.generateAudioMom)(id);
      onUpdate?.();
    } catch (e) { alert(`MoM failed: ${e.message}`); }
    finally { setMomBusy(false); }
  }

  async function handleEnableQA() {
    setEmbBusy(true);
    try { await meetingBotApi.generateEmbeddings(id); onUpdate?.(); }
    catch (e) { alert(`Failed: ${e.message}`); }
    finally { setEmbBusy(false); }
  }

  const txGenerated = txStatus === "generated";
  const txGenerating = txStatus === "generating" || txBusy;
  const momGenerating = momStatus === "generating" || momBusy;
  const canGenTx  = a[`can_generate_${type}_transcript`] && !txBusy;
  const canGenMom = a[`can_generate_${type}_mom`]        && !momBusy && !momGenerating;

  return (
    <div className="mdp-media-tab">

      {/* Player */}
      <div className="mdp-player-wrap">
        <RecordingPlayer
          type={type}
          url={meeting[`${type}_recording_url`]}
          status={meeting[`${type}_recording_status`]}
        />
      </div>

      {/* Transcript card */}
      <Panel icon="📄" title={`${label} Transcript`} badge={txStatus}>
        {txGenerating && (
          <div className="mdp-loading-row"><Spin />
            Transcribing — this may take a few minutes…
          </div>
        )}
        {txStatus === "failed" && (
          <EmptyBox icon="⚠️" title="Transcription failed." sub="Please try again." />
        )}
        {!txGenerated && !txGenerating && (
          <div className="mdp-gen-block">
            <EmptyBox icon="🎙️"
              title="Transcript not generated yet."
              sub={`Click the button to start ${label.toLowerCase()} transcription.`}
            />
            <button onClick={handleGenTranscript} disabled={!canGenTx}>
              {txBusy ? <><Spin sm />Starting…</> : `Generate ${label} Transcript`}
            </button>
          </div>
        )}
        {txGenerated && (
          <div className="mdp-scroll">
            <TranscriptWithLanguage
              meetingId={id}
              source={type}
              initialChunks={transcript?.chunks}
            />
          </div>
        )}
      </Panel>

      {/* Chat bot */}
      <Panel icon="💬" title="Ask Questions" badge={embStatus === "generated" ? "generated" : undefined}>
        <ChatBot
          meetingId={id}
          source={label.toLowerCase()}
          transcriptGenerated={txGenerated}
          embStatus={embBusy ? "generating" : embStatus}
          onEnableQA={handleEnableQA}
        />
      </Panel>

      {/* MoM card */}
      <Panel icon="📋" title="Minutes of Meeting" badge={momStatus}>
        {momGenerating && (
          <div className="mdp-loading-row"><Spin />Generating MoM…</div>
        )}
        {momStatus === "generated" && mom ? (
          <div className="mdp-scroll">
            <MomViewer mom={mom} />
          </div>
        ) : !momGenerating && (
          <EmptyBox icon="📋"
            title="MoM not generated yet."
            sub={txGenerated
              ? "Click Generate MoM to summarise this recording."
              : `Generate the ${label.toLowerCase()} transcript first.`}
          />
        )}
        <div className="mdp-panel-foot">
          <button onClick={handleGenMom} disabled={!canGenMom}>
            {momGenerating ? <><Spin sm />Generating…</> : "Generate MoM"}
          </button>
        </div>
      </Panel>
    </div>
  );
}

// ── Root export ───────────────────────────────────────────────────────────────

const TABS = [
  { key: "live",  icon: "📝", label: "Live Transcript" },
  { key: "audio", icon: "🎵", label: "Audio"           },
  { key: "video", icon: "🎬", label: "Video"           },
];

export default function MeetingDetailPage({ meeting, onUpdate }) {
  const [activeTab, setActiveTab] = useState("live");

  return (
    <div className="mdp-root">
      {/* Tab bar */}
      <div className="mdp-tabbar" role="tablist">
        {TABS.map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={activeTab === t.key}
            className={`mdp-tabbtn${activeTab === t.key ? " mdp-tabbtn-active" : ""}`}
            onClick={() => setActiveTab(t.key)}
          >
            <span className="mdp-tab-icon">{t.icon}</span>
            {t.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="mdp-content">
        {activeTab === "live"  && <LiveTab  meeting={meeting} onUpdate={onUpdate} />}
        {activeTab === "audio" && <MediaTab type="audio" meeting={meeting} onUpdate={onUpdate} />}
        {activeTab === "video" && <MediaTab type="video" meeting={meeting} onUpdate={onUpdate} />}
      </div>
    </div>
  );
}
