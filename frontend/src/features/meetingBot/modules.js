// Single source of truth for the meeting modules. Drives both the card grid on
// the meeting detail page and the individual module pages.
//
// Each module: { key (route segment), title, statusField (on meeting detail),
// info (short description), group (for ordering/labels) }.
export const MODULES = [
  {
    key: "live-transcript",
    title: "Live Transcript",
    statusField: "live_transcript_status",
    info: "Real-time transcript captured during the meeting.",
    group: "Live",
  },
  {
    key: "audio-recording",
    title: "Audio Recording",
    statusField: "audio_recording_status",
    info: "Recorded meeting audio (MP3) with player.",
    group: "Recordings",
  },
  // Combined video card — shows recording player + transcript (with language
  // tabs) + MoM all in one page instead of three separate cards.
  {
    key: "video",
    title: "Video Recording",
    statusField: "video_transcript_status",
    info: "Video recording, transcript with language tabs, and Minutes of Meeting.",
    group: "Video",
  },
  {
    key: "audio-transcript",
    title: "Audio Transcript",
    statusField: "audio_transcript_status",
    info: "High-accuracy transcript from the audio file.",
    group: "Audio",
  },
  {
    key: "ai-transcript",
    title: "AI Transcript",
    statusField: "ai_transcript_status",
    info: "AI-proofread transcript — wrong words underlined with the correct word.",
    group: "Audio",
  },
  {
    key: "audio-mom",
    title: "MoM",
    statusField: "audio_mom_status",
    info: "Minutes of Meeting — auto-generated from the meeting.",
    group: "MoM",
  },
  {
    key: "ask",
    title: "Ask AI",
    statusField: "embeddings_status",
    info: "Semantic Q&A and search over the meeting transcripts.",
    group: "AI",
  },
];

export const MODULE_BY_KEY = Object.fromEntries(MODULES.map((m) => [m.key, m]));
