import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { meetingBotApi } from "../services/meetingBotApi.js";
import MeetingCreateForm from "../components/MeetingCreateForm.jsx";
import LiveMeetingScreen from "../components/LiveMeetingScreen.jsx";
import MeetingDetailPage from "../components/MeetingDetailPage.jsx";
import StatusBadge from "../components/StatusBadge.jsx";
import ConfirmModal from "../components/ConfirmModal.jsx";
import Toast from "../components/Toast.jsx";

const TERMINAL = ["completed", "failed"];
const ACTIVE = ["created", "joining", "waiting_for_admit", "live"]; // meeting still running

export default function MeetingBotPage() {
  const { id } = useParams();
  return id ? <Detail id={id} /> : <ListAndCreate />;
}

// ---------------- List + create ----------------
function ListAndCreate() {
  const [meetings, setMeetings] = useState([]);
  const [query, setQuery] = useState("");
  const [pendingDelete, setPendingDelete] = useState(null); // meeting being deleted
  const [deleting, setDeleting] = useState(false);
  const navigate = useNavigate();

  async function load() {
    try {
      setMeetings(await meetingBotApi.listMeetings());
    } catch (_) {}
  }
  useEffect(() => {
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);

  function askDelete(e, meeting) {
    // Inside a <Link>, so stop it from navigating into the meeting.
    e.preventDefault();
    e.stopPropagation();
    setPendingDelete(meeting);
  }

  async function confirmDelete() {
    const meetingId = pendingDelete._id || pendingDelete.id;
    setDeleting(true);
    try {
      await meetingBotApi.deleteMeeting(meetingId);
      setMeetings((list) => list.filter((m) => (m._id || m.id) !== meetingId));
    } catch (_) {
    } finally {
      setDeleting(false);
      setPendingDelete(null);
      load();
    }
  }

  // Filter by title, status, or date (matches both the raw ISO and the
  // human-readable localized date string so "20/06/2026", "june", "completed"
  // all work).
  const q = query.trim().toLowerCase();
  const filtered = !q
    ? meetings
    : meetings.filter((m) => {
        const created = m.created_at ? new Date(m.created_at) : null;
        const dateForms = created
          ? [
              created.toLocaleString(),            // 20/06/2026, 07:18:43
              created.toLocaleDateString(),        // 20/06/2026
              // Month-name forms so "20 june", "june 2026", "jun" all match:
              created.toLocaleDateString("en-US", { day: "numeric", month: "long", year: "numeric" }),  // June 20, 2026
              created.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" }),  // 20 June 2026
              created.toLocaleDateString("en-GB", { day: "numeric", month: "short" }),                  // 20 Jun
              created.toLocaleDateString("en-US", { month: "long", year: "numeric" }),                  // June 2026
            ]
          : [];
        const haystack = [m.meeting_title, m.status, m.created_at, ...dateForms]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        return haystack.includes(q);
      });

  return (
    <div>
      <h1>Advanced Meeting Bot</h1>
      <MeetingCreateForm onCreated={(m) => navigate(`/meetings/${m.meeting_id}`)} />

      <div className="meeting-search">
        <span className="meeting-search-icon" aria-hidden="true">🔍</span>
        <input
          type="text"
          className="meeting-search-input"
          placeholder="Search meetings by name, date or status…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Search meetings"
        />
        {query && (
          <button
            type="button"
            className="meeting-search-clear"
            onClick={() => setQuery("")}
            aria-label="Clear search"
          >
            ✕
          </button>
        )}
      </div>

      <div className="meeting-grid">
        {filtered.map((m) => (
          <Link key={m._id || m.id} to={`/meetings/${m._id || m.id}`} className="card meeting-card">
            <button
              type="button"
              className="meeting-card-delete"
              onClick={(e) => askDelete(e, m)}
              title="Delete meeting"
              aria-label="Delete meeting"
            >
              ✕
            </button>
            <h3>{m.meeting_title}</h3>
            <StatusBadge status={m.status} />
            <p className="muted">{m.created_at ? new Date(m.created_at).toLocaleString() : ""}</p>
          </Link>
        ))}
        {meetings.length === 0 && <p className="muted">No meetings yet.</p>}
        {meetings.length > 0 && filtered.length === 0 && (
          <p className="muted">No meetings match “{query}”.</p>
        )}
      </div>

      {pendingDelete && (
        <ConfirmModal
          title="Delete Meeting?"
          message={`Are you sure you want to delete “${pendingDelete.meeting_title}”? This permanently removes its transcript, recordings and MoM.`}
          confirmLabel="Delete"
          busyLabel="Deleting…"
          danger
          busy={deleting}
          onConfirm={confirmDelete}
          onCancel={() => (deleting ? null : setPendingDelete(null))}
        />
      )}
    </div>
  );
}

// ---------------- Detail — single-page dashboard ----------------
function Detail({ id }) {
  const [meeting, setMeeting] = useState(null);
  const [showStop, setShowStop] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [toast, setToast] = useState(null);

  async function load() {
    try {
      const m = await meetingBotApi.getMeeting(id);
      setMeeting(m);
      return m;
    } catch (_) {
      return null;
    }
  }

  useEffect(() => {
    let timer;
    async function tick() {
      const m = await load();
      if (m && !TERMINAL.includes(m.status)) timer = setTimeout(tick, 4000);
    }
    tick();
    return () => clearTimeout(timer);
  }, [id]);

  async function handleStop() {
    setStopping(true);
    try {
      await meetingBotApi.stopMeeting(id);
      setShowStop(false);
      setToast({ message: "Meeting bot stopped successfully.", type: "success" });
      await load();
    } catch (_) {
      setToast({ message: "Failed to stop meeting bot. Please try again.", type: "error" });
    } finally {
      setStopping(false);
    }
  }

  if (!meeting) return <p>Loading…</p>;

  const processing = meeting.status === "processing";
  const active     = ACTIVE.includes(meeting.status);
  const dateStr    = meeting.created_at
    ? new Date(meeting.created_at).toLocaleString()
    : null;

  return (
    <div>
      {/* ── Page header ── */}
      <div className="detail-header">
        <Link to="/" className="dash-back">← All Meetings</Link>
        <div className="dash-title-block">
          <h1>{meeting.meeting_title}</h1>
          {dateStr && <p className="muted dash-date">{dateStr}</p>}
        </div>
        <StatusBadge status={meeting.status} />
        {active && (
          <button className="btn-stop" onClick={() => setShowStop(true)} disabled={stopping}>
            {stopping ? "Stopping…" : "Stop Meeting"}
          </button>
        )}
      </div>

      {meeting.error && <p className="error">Error: {meeting.error}</p>}

      {showStop && (
        <ConfirmModal
          title="Stop Meeting Bot?"
          message="Are you sure you want to stop the meeting bot? This will remove the bot from the meeting and stop live transcription/recording."
          confirmLabel="Stop Meeting"
          busyLabel="Stopping…"
          danger
          busy={stopping}
          onConfirm={handleStop}
          onCancel={() => setShowStop(false)}
        />
      )}
      <Toast message={toast?.message} type={toast?.type} onClose={() => setToast(null)} />

      {processing && (
        <div className="mb-preparing">
          ⏳ <strong>Meeting ended.</strong> Preparing recordings, transcript &amp; MoM…
        </div>
      )}

      {/* ── Main content ── */}
      {active ? (
        <LiveMeetingScreen meeting={meeting} onUpdate={load} />
      ) : (
        <MeetingDetailPage meeting={meeting} onUpdate={load} />
      )}
    </div>
  );
}
