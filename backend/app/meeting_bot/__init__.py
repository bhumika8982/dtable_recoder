"""Advanced meeting-bot flow.

A self-contained, modular package that adds the production meeting-bot flow
(live transcript + audio/video recordings + optional re-transcription +
source-separated MoM) under the ``/api/meeting-bot`` prefix.

It deliberately REUSES the existing hardened services (Recall, WhisperX,
diarization, S3, Groq MoM) rather than duplicating them, and never touches the
existing ``/api/meetings`` flow.
"""
