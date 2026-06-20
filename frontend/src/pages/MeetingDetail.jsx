import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api.js";

const TABS = ["Recording", "Transcript", "MOM"];
const TERMINAL = ["completed", "failed"];
// Statuses that mean the pipeline is still working towards the transcript.
const TRANSCRIBING_STATES = [
  "created",
  "bot_scheduled",
  "in_call",
  "recording_ready",
  "downloading",
  "extracting_audio",
  "transcribing",
  "diarizing",
  "merging",
];

export default function MeetingDetail() {
  const { id } = useParams();
  const [meeting, setMeeting] = useState(null);
  const [tab, setTab] = useState("Recording");
  const [transcript, setTranscript] = useState(null);
  const [mom, setMom] = useState(null);
  const [recordingUrl, setRecordingUrl] = useState(null);
  const [busy, setBusy] = useState(false);
  // Bumping this restarts the status poller after a manual (re)run.
  const [reloadTick, setReloadTick] = useState(0);

  async function loadMeeting() {
    try {
      const m = await api.getMeeting(id);
      setMeeting(m);
      return m;
    } catch (_) {
      return null;
    }
  }

  // (Re)run the full pipeline: Recording -> Transcript -> MOM.
  async function handleProcess() {
    // If a run looks like it's still going, confirm before starting another so
    // we don't kick off two pipelines by accident. (A stuck status after a
    // server restart also lands here, and the user can confirm to recover.)
    if (meeting && !TERMINAL.includes(meeting.status)) {
      const ok = window.confirm(
        `This meeting is currently "${meeting.status}". Re-run the pipeline anyway?`
      );
      if (!ok) return;
    }
    setBusy(true);
    try {
      await api.processMeeting(id);
      // Drop cached artifacts so the tabs re-fetch the fresh run.
      setTranscript(null);
      setMom(null);
      setReloadTick((t) => t + 1); // restart polling
    } catch (e) {
      alert(`Could not start processing: ${e.message}`);
    } finally {
      setBusy(false);
    }
  }

  // Poll meeting status until processing completes.
  useEffect(() => {
    let timer;
    async function tick() {
      const m = await loadMeeting();
      if (m && !TERMINAL.includes(m.status)) {
        timer = setTimeout(tick, 4000);
      }
    }
    tick();
    return () => clearTimeout(timer);
  }, [id, reloadTick]);

  // Lazy-load each artifact when its tab is opened.
  useEffect(() => {
    if (!meeting) return;
    const safe = (p) => p.catch(() => null);
    if (tab === "Recording" && !recordingUrl)
      safe(api.getRecordingUrl(id)).then((r) => r && setRecordingUrl(r.url));
    if (tab === "Transcript" && !transcript) safe(api.getTranscript(id)).then(setTranscript);
    if (tab === "MOM" && !mom) safe(api.getMom(id)).then(setMom);
  }, [tab, meeting]);

  if (!meeting) return <p>Loading…</p>;

  return (
    <div>
      <div className="detail-header">
        <h1>{meeting.title}</h1>
        <span className={`badge status-${meeting.status}`}>{meeting.status}</span>
        <div className="exports">
          <button
            className="btn-process"
            onClick={handleProcess}
            disabled={busy}
            title="Run Recording → Transcript → MOM"
          >
            {busy
              ? "Starting…"
              : !TERMINAL.includes(meeting.status)
              ? "Processing… (click to re-run)"
              : meeting.status === "failed"
              ? "Retry"
              : "Generate"}
          </button>
          <a href={api.exportUrl(id, "pdf")} target="_blank" rel="noreferrer">
            Export PDF
          </a>
          <a href={api.exportUrl(id, "docx")} target="_blank" rel="noreferrer">
            Export DOCX
          </a>
        </div>
      </div>
      {meeting.error && <p className="error">Error: {meeting.error}</p>}

      <nav className="tabs">
        {TABS.map((t) => (
          <button
            key={t}
            className={tab === t ? "tab active" : "tab"}
            onClick={() => setTab(t)}
          >
            {t}
          </button>
        ))}
      </nav>

      <div className="tab-body">
        {tab === "Recording" &&
          (recordingUrl ? (
            <video controls src={recordingUrl} style={{ width: "100%" }} />
          ) : (
            <p className="muted">Recording not ready yet.</p>
          ))}

        {tab === "Transcript" &&
          (transcript && transcript.segments && transcript.segments.length > 0 ? (
            <>
              {meeting.diarization_error && (
                <p className="warn">{meeting.diarization_error}</p>
              )}
              <div className="transcript">
                {transcript.segments.map((s, i) => (
                  <p key={i} className="transcript-line">
                    <span className="ts">[{formatTimestamp(s.start)}]</span>{" "}
                    <span className="speaker">
                      {s.speaker_label || friendlySpeaker(s.speaker)}:
                    </span>{" "}
                    <span className="utterance">{s.text}</span>
                  </p>
                ))}
              </div>
            </>
          ) : meeting.status === "failed" ? (
            <p className="error">Transcription failed: {meeting.error || "unknown error"}</p>
          ) : TRANSCRIBING_STATES.includes(meeting.status) ? (
            <p className="muted">⏳ Generating transcript… (status: {meeting.status})</p>
          ) : (
            <p className="muted">No transcript available (no speech detected).</p>
          ))}

        {tab === "MOM" &&
          (mom && (mom.summary || (mom.key_points && mom.key_points.length)) ? (
            <div className="mom">
              <h2 className="mom-title">{meeting.title}</h2>
              <p className="mom-meta">
                {formatDateTime(meeting.join_at || meeting.created_at)}
              </p>
              {mom.attendees && mom.attendees.length > 0 && (
                <p className="mom-attendees">
                  <strong>Attendees:</strong> {mom.attendees.join(", ")}
                </p>
              )}

              <h3>Overview</h3>
              <p>{mom.summary || "—"}</p>

              <BulletSection title="Key Discussion Points" items={mom.key_points} />
              <BulletSection title="Action Items" items={mom.action_items} />
              <BulletSection title="Next Steps" items={mom.next_steps} />
            </div>
          ) : meeting.status === "failed" ? (
            <p className="error">MOM generation failed: {meeting.error || "unknown error"}</p>
          ) : meeting.status === "completed" ? (
            <p className="muted">No MOM available (transcript was empty).</p>
          ) : (
            <p className="muted">⏳ Generating MOM… (status: {meeting.status})</p>
          ))}
      </div>
    </div>
  );
}

// Seconds -> "HH:MM:SS" (e.g. 72.4 -> "00:01:12").
function formatTimestamp(seconds) {
  const s = Math.max(0, Math.round(seconds || 0));
  const hh = String(Math.floor(s / 3600)).padStart(2, "0");
  const mm = String(Math.floor((s % 3600) / 60)).padStart(2, "0");
  const ss = String(s % 60).padStart(2, "0");
  return `${hh}:${mm}:${ss}`;
}

// "SPEAKER_00" -> "Speaker 1"; falls back to the raw label.
function friendlySpeaker(label) {
  if (!label || label === "UNKNOWN") return "Unknown";
  const m = String(label).match(/(\d+)\s*$/);
  return m ? `Speaker ${parseInt(m[1], 10) + 1}` : label;
}

function formatDateTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d.getTime())
    ? ""
    : d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function BulletSection({ title, items }) {
  if (!items || items.length === 0) return null;
  return (
    <>
      <h3>{title}</h3>
      <ul>
        {items.map((x, i) => (
          <li key={i}>{x}</li>
        ))}
      </ul>
    </>
  );
}
