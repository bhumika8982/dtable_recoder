// Lightweight API client for the FastAPI backend.
const BASE = import.meta.env.VITE_API_BASE || "";

async function request(path, options = {}) {
  const method = options.method || "GET";
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  // "Frontend API response received" — visible in the browser devtools console.
  console.debug(`[api] ${method} ${path} -> ${res.status}`);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail || detail;
    } catch (_) {}
    throw new Error(detail);
  }
  return res.status === 204 ? null : res.json();
}

export const api = {
  listMeetings: () => request("/api/meetings"),
  getMeeting: (id) => request(`/api/meetings/${id}`),
  createMeeting: (body) =>
    request("/api/meetings", { method: "POST", body: JSON.stringify(body) }),
  processMeeting: (id) => request(`/api/meetings/${id}/process`, { method: "POST" }),
  deleteMeeting: (id) => request(`/api/meetings/${id}`, { method: "DELETE" }),
  getTranscript: (id) => request(`/api/meetings/${id}/transcript`),
  getMom: (id) => request(`/api/meetings/${id}/mom`),
  getRecordingUrl: (id) => request(`/api/meetings/${id}/recording-url`),
  exportUrl: (id, fmt) => `${BASE}/api/meetings/${id}/export.${fmt}`,
};
