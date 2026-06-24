// API client for the advanced meeting-bot flow (/api/meeting-bot).
const BASE = import.meta.env.VITE_API_BASE || "";
const ROOT = `${BASE}/api/meeting-bot`;

async function request(path, options = {}) {
  const res = await fetch(`${ROOT}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail || detail;
    } catch (_) {}
    throw new Error(detail);
  }
  return res.status === 204 ? null : res.json();
}

export const meetingBotApi = {
  listMeetings: () => request("/meetings"),
  createMeeting: (body) => request("/meetings", { method: "POST", body: JSON.stringify(body) }),
  getMeeting: (id) => request(`/meetings/${id}`),
  deleteMeeting: (id) => request(`/meetings/${id}`, { method: "DELETE" }),
  stopMeeting: (id) => request(`/meetings/${id}/stop`, { method: "POST" }),

  getTranscript: (id, source, lang) =>
    request(`/meetings/${id}/transcripts/${source}${lang && lang !== "native" ? `?lang=${lang}` : ""}`),
  getRecordings: (id) => request(`/meetings/${id}/recordings`),
  getMom: (id, source) => request(`/meetings/${id}/mom/${source}`),

  transcribeAudio: (id) => request(`/meetings/${id}/audio/transcribe`, { method: "POST" }),
  generateAudioMom: (id) => request(`/meetings/${id}/audio/generate-mom`, { method: "POST" }),
  transcribeVideo: (id) => request(`/meetings/${id}/video/transcribe`, { method: "POST" }),
  generateVideoMom: (id) => request(`/meetings/${id}/video/generate-mom`, { method: "POST" }),
  generateAiTranscript: (id) => request(`/meetings/${id}/ai-transcript/generate`, { method: "POST" }),

  generateEmbeddings: (id) => request(`/meetings/${id}/embeddings`, { method: "POST" }),
  ask: (id, question) =>
    request(`/meetings/${id}/ask`, { method: "POST", body: JSON.stringify({ question }) }),
  askAudio: (id, question) =>
    request(`/meetings/${id}/audio/ask`, { method: "POST", body: JSON.stringify({ question }) }),
  askVideo: (id, question) =>
    request(`/meetings/${id}/video/ask`, { method: "POST", body: JSON.stringify({ question }) }),

  generateLiveMom: (id) => request(`/meetings/${id}/live/generate-mom`, { method: "POST" }),

  // AI MoM: MoM generated from the AI-proofread (corrected) transcript.
  generateAiMom: (id) => request(`/meetings/${id}/ai/generate-mom`, { method: "POST" }),
  getAiMom: (id) => request(`/meetings/${id}/mom/ai`),

  // Download transcript as a .txt file — returns the full URL so the caller can
  // trigger a browser download directly without fetching through fetch().
  downloadTranscriptUrl: (id, source) => `${ROOT}/meetings/${id}/transcripts/${source}/download`,

  // Transcript language translation — chunks cached in MongoDB after first call.
  translateAudioTranscript: (id, targetLanguage) =>
    request(`/meetings/${id}/audio/transcript/translate`, {
      method: "POST",
      body: JSON.stringify({ target_language: targetLanguage }),
    }),
  translateVideoTranscript: (id, targetLanguage) =>
    request(`/meetings/${id}/video/transcript/translate`, {
      method: "POST",
      body: JSON.stringify({ target_language: targetLanguage }),
    }),

  // Server-Sent Events stream for live updates.
  eventsUrl: (id) => `${ROOT}/meetings/${id}/events`,
};
