# Meeting Bot

An AI meeting assistant that sends a bot to your call, records it, and turns the
recording into a searchable transcript, Minutes of Meeting (MOM), action items,
client requirements, decisions, risks, and open questions — each verified against
the transcript to catch hallucinations. Includes an **Ask AI** panel for RAG over
your meeting history.

> **No Docker. No Celery. No Redis. No queue system.** Processing runs in-process
> via FastAPI `BackgroundTasks`.

## Stack

| Concern | Choice |
| --- | --- |
| Meeting join + recording | **Recall.ai** |
| Transcription | **WhisperX** |
| Speaker diarization | **pyannote.audio** |
| MOM / tasks / requirements / decisions / verification | **GPT-4o** |
| Vector search (RAG) | **Qdrant** |
| Recording / audio / transcript / export storage | **AWS S3** |
| Structured data | **MongoDB** |
| Background processing | **FastAPI BackgroundTasks** |
| Backend | **FastAPI** |
| Frontend | **React (Vite)** |

## Architecture

```
React (Vite)  ──HTTP──▶  FastAPI
                              │  create meeting
                              ├─▶ Recall.ai  (bot joins + records the call)
                              │
        Recall webhook ──────▶│  "recording ready"
                              │
                              ▼  BackgroundTasks: process_meeting()
   1. download recording from Recall ─▶ S3
   2. ffmpeg: extract 16kHz mono WAV ─▶ S3
   3. WhisperX transcribe
   4. pyannote diarize
   5. merge transcript + speakers ───▶ MongoDB + S3
   6. GPT-4o → MOM
   7. GPT-4o → tasks / requirements / decisions / risks / open questions
   8. GPT-4o → verify each item vs transcript (hallucination check)
   9. embed transcript chunks ───────▶ Qdrant
                              │
                              ▼
                MongoDB  ◀── results ──▶  React UI (recording, transcript,
                                          MOM, tasks, requirements, Ask AI)
```

## Prerequisites (installed locally — no containers required)

- **Python 3.11**
- **Node 18+**
- **FFmpeg** on your `PATH` (`ffmpeg -version`)
- **MongoDB** running locally (`mongodb://localhost:27017`) or MongoDB Atlas
- **Qdrant** running locally (`http://localhost:6333`) or Qdrant Cloud
  - Native binary: download from the Qdrant releases page and run `./qdrant`.
- **GPU optional.** WhisperX/pyannote use CUDA if available, otherwise CPU.
- API keys: **Recall.ai**, **OpenAI**, and a **HuggingFace token** (for the gated
  pyannote diarization model — accept the model terms on its HF page first).

## Backend setup

```bash
cd backend
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate

# 1) Install PyTorch FIRST, matched to your hardware.
#    GPU (CUDA 12.1):
pip install torch --index-url https://download.pytorch.org/whl/cu121
#    CPU only:
# pip install torch --index-url https://download.pytorch.org/whl/cpu

# 2) Install the rest.
pip install -r requirements.txt

# 3) Configure environment.
cp .env.example .env   # then fill in keys

# 4) Run the API.
uvicorn app.main:app --reload --port 8000
```

API docs: http://localhost:8000/docs · health check: http://localhost:8000/health

### Notes on WhisperX / pyannote

- `WHISPER_DEVICE=auto` selects CUDA when a GPU is present, else CPU. On CPU set
  `WHISPER_COMPUTE_TYPE=int8` (auto already does this) and expect slower runs.
- `HF_TOKEN` is required so pyannote can download `pyannote/speaker-diarization-3.1`.
  Accept the model's terms on HuggingFace with the same account.
- Models load lazily on first use and stay warm for subsequent meetings.

## Frontend setup

```bash
cd frontend
npm install
cp .env.example .env   # optional; dev proxy works out of the box
npm run dev            # http://localhost:5173
```

The Vite dev server proxies `/api/*` to the backend on port 8000.

## How a meeting flows through the system

1. In the UI, enter a meeting title + join URL and click **Send bot**. The backend
   creates a meeting record and dispatches a Recall.ai bot.
2. Recall joins the call and records it. When done, Recall calls
   `POST /api/webhooks/recall`, which schedules `process_meeting` as a background
   task (no queue/worker involved).
3. The pipeline downloads the recording, extracts audio, transcribes, diarizes,
   merges, generates MOM + items, verifies them, and indexes embeddings.
4. The meeting's `status` field advances through each stage; the UI polls it.
5. When `completed`, open the meeting to see the recording, transcript, MOM,
   tasks, requirements, decisions, and **Ask AI**. Export to PDF/DOCX.

### Local testing without a real webhook

You can drive the pipeline manually once a bot has recorded:

```bash
curl -X POST http://localhost:8000/api/meetings/<MEETING_ID>/process
```

Or simulate the Recall webhook:

```bash
curl -X POST http://localhost:8000/api/webhooks/recall \
  -H "Content-Type: application/json" \
  -d '{"event":"bot.done","data":{"bot_id":"<RECALL_BOT_ID>"}}'
```

> For Recall to reach your local webhook, expose port 8000 with a tunnel (e.g.
> `ngrok http 8000`) and set that URL in your Recall webhook settings.

## API reference (summary)

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/meetings` | Create meeting + dispatch Recall bot |
| GET | `/api/meetings` | List meetings |
| GET | `/api/meetings/{id}` | Get meeting + status |
| GET | `/api/meetings/{id}/transcript` | Merged transcript |
| GET | `/api/meetings/{id}/mom` | Minutes of Meeting |
| GET | `/api/meetings/{id}/extraction` | Tasks/requirements/decisions/risks/questions |
| GET | `/api/meetings/{id}/recording-url` | Presigned S3 URL for the recording |
| GET | `/api/meetings/{id}/export.pdf` | Export PDF |
| GET | `/api/meetings/{id}/export.docx` | Export DOCX |
| POST | `/api/meetings/{id}/process` | Manually (re)trigger processing |
| POST | `/api/webhooks/recall` | Recall.ai webhook receiver |
| POST | `/api/ask` | Ask AI / RAG over meeting history |

## Tests

The test suite mocks all external services (Recall, OpenAI, WhisperX, pyannote,
S3, Mongo) so it runs fast and offline. It does **not** require torch/whisperx/
pyannote to be installed.

```bash
cd backend
pip install pytest pytest-asyncio mongomock-motor
pytest -q
```

Covered: meeting creation, Recall bot creation, webhook handling, S3 upload,
audio extraction, WhisperX transcription, pyannote diarization, transcript
merging, MOM generation, task extraction, requirement extraction, and
verification (hallucination checking).

## Project layout

```
backend/
  app/
    config.py            # env-driven settings
    main.py              # FastAPI app + lifespan + routers
    db/mongo.py          # Motor connection + indexes
    models/              # enums + ObjectId helpers
    schemas/             # Pydantic request/response models
    repositories/        # MongoDB data access
    services/
      recall_service.py        # Recall.ai bot + recording
      s3_service.py            # AWS S3 upload/download/presign
      audio_service.py         # ffmpeg audio extraction
      transcription_service.py # WhisperX
      diarization_service.py   # pyannote.audio
      merge_service.py         # transcript + speaker merge
      llm_service.py           # GPT-4o client (JSON + embeddings)
      prompts.py               # prompt templates
      generation_service.py    # MOM + item extraction
      verification_service.py  # hallucination checking
      rag_service.py           # chunk + embed + Qdrant + Ask AI
      export_service.py        # PDF / DOCX
      processing.py            # BackgroundTasks pipeline (orchestration)
    routers/             # meetings, webhooks, ask_ai, exports
  tests/
frontend/
  src/
    api.js               # API client
    pages/               # MeetingList, MeetingDetail
    components/          # AskAI, EvidenceBadge
```

## Configuration reference

All backend settings are environment variables (see `backend/.env.example`).
Notable ones: `MONGO_URI`, `S3_BUCKET`, `RECALL_API_KEY`, `OPENAI_API_KEY`,
`HF_TOKEN`, `WHISPER_DEVICE`, `WHISPER_COMPUTE_TYPE`, `QDRANT_URL`.
