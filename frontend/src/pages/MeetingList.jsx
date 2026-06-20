import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";

const STATUS_LABELS = {
  created: "Created",
  bot_scheduled: "Bot scheduled",
  in_call: "In call",
  recording_ready: "Recording ready",
  completed: "Completed",
  failed: "Failed",
};

export default function MeetingList() {
  const [meetings, setMeetings] = useState([]);
  const [form, setForm] = useState({
    title: "",
    meeting_url: "",
    bot_name: "Meeting Bot",
    num_speakers: "",
  });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      setMeetings(await api.listMeetings());
    } catch (e) {
      setError(e.message);
    }
  }

  useEffect(() => {
    load();
    const t = setInterval(load, 5000); // poll for status changes
    return () => clearInterval(t);
  }, []);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      // Omit num_speakers when blank so diarization auto-detects.
      const { num_speakers, ...rest } = form;
      const body = num_speakers
        ? { ...rest, num_speakers: Number(num_speakers) }
        : rest;
      await api.createMeeting(body);
      setForm({ title: "", meeting_url: "", bot_name: "Meeting Bot", num_speakers: "" });
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete(e, m) {
    // The card is a link; don't navigate when deleting.
    e.preventDefault();
    e.stopPropagation();
    if (!window.confirm(`Delete meeting "${m.title}"? This cannot be undone.`)) return;
    try {
      await api.deleteMeeting(m.id);
      setMeetings((prev) => prev.filter((x) => x.id !== m.id));
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <div>
      <h1>Meetings</h1>

      <form className="card create-form" onSubmit={submit}>
        <h2>Send bot to a meeting</h2>
        <input
          placeholder="Meeting title"
          value={form.title}
          required
          onChange={(e) => setForm({ ...form, title: e.target.value })}
        />
        <input
          placeholder="Meeting URL (Zoom / Meet / Teams)"
          value={form.meeting_url}
          required
          onChange={(e) => setForm({ ...form, meeting_url: e.target.value })}
        />
        <input
          placeholder="Bot name"
          value={form.bot_name}
          onChange={(e) => setForm({ ...form, bot_name: e.target.value })}
        />
        <input
          type="number"
          min="1"
          max="20"
          placeholder="Number of speakers (optional, e.g. 1)"
          value={form.num_speakers}
          onChange={(e) => setForm({ ...form, num_speakers: e.target.value })}
        />
        <button disabled={busy}>{busy ? "Sending..." : "Send bot"}</button>
      </form>

      {error && <p className="error">{error}</p>}

      <div className="meeting-grid">
        {meetings.map((m) => (
          <Link key={m.id} to={`/meetings/${m.id}`} className="card meeting-card">
            <button
              className="btn-delete"
              title="Delete meeting"
              onClick={(e) => handleDelete(e, m)}
            >
              ✕
            </button>
            <h3>{m.title}</h3>
            <span className={`badge status-${m.status}`}>
              {STATUS_LABELS[m.status] || m.status}
            </span>
            <p className="muted">{new Date(m.created_at).toLocaleString()}</p>
          </Link>
        ))}
        {meetings.length === 0 && <p className="muted">No meetings yet.</p>}
      </div>
    </div>
  );
}
