import { useState } from "react";
import { meetingBotApi } from "../services/meetingBotApi.js";

export default function MeetingCreateForm({ onCreated }) {
  const [form, setForm] = useState({ meeting_title: "", meeting_link: "", num_speakers: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { num_speakers, ...rest } = form;
      const body = num_speakers ? { ...rest, num_speakers: Number(num_speakers) } : rest;
      const res = await meetingBotApi.createMeeting(body);
      setForm({ meeting_title: "", meeting_link: "", num_speakers: "" });
      onCreated?.(res);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card create-form" onSubmit={submit}>
      <h2>Send bot to a meeting</h2>
      <input
        placeholder="Meeting title"
        value={form.meeting_title}
        required
        onChange={(e) => setForm({ ...form, meeting_title: e.target.value })}
      />
      <input
        placeholder="Meeting link (Zoom / Meet / Teams)"
        value={form.meeting_link}
        required
        onChange={(e) => setForm({ ...form, meeting_link: e.target.value })}
      />
      <input
        type="number"
        min="1"
        max="50"
        placeholder="Number of speakers (optional)"
        value={form.num_speakers}
        onChange={(e) => setForm({ ...form, num_speakers: e.target.value })}
      />
      <button disabled={busy}>{busy ? "Sending…" : "Send bot"}</button>
      {error && <p className="error">{error}</p>}
    </form>
  );
}
