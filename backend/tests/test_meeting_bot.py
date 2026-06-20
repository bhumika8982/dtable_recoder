"""Tests for the advanced meeting-bot flow.

External services (Recall, S3, WhisperX, LLM) are mocked; MongoDB is the
in-memory ``mongomock_motor`` from conftest. Covers creation, webhooks (status +
live transcript), idempotency-friendly reads, job guards, and pure helpers.
"""
from __future__ import annotations

import pytest

import app.meeting_bot.router as mb_router
import app.meeting_bot.processing as mb_processing
from app.meeting_bot.mom_service import MomService
from app.meeting_bot.recall_service import MeetingBotRecall
from app.meeting_bot.transcription_service import segments_to_chunks
from app.meeting_bot.models import Source
from app.meeting_bot.utils import chunk_text_by_chars, friendly_speaker


# --------------------------------------------------------------------------- #
# Helpers / fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def mock_recall(monkeypatch):
    async def _create_bot(self, meeting_url, bot_name):
        return {"id": "bot-123"}

    monkeypatch.setattr(MeetingBotRecall, "create_bot", _create_bot)
    return _create_bot


def _create_meeting(client) -> dict:
    resp = client.post(
        "/api/meeting-bot/meetings",
        json={"meeting_title": "Client Sync", "meeting_link": "https://meet.google.com/abc"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# --------------------------------------------------------------------------- #
# Meeting creation
# --------------------------------------------------------------------------- #
def test_create_meeting_dispatches_bot(client, mock_recall):
    body = _create_meeting(client)
    assert body["bot_id"] == "bot-123"
    assert body["status"] == "joining"

    detail = client.get(f"/api/meeting-bot/meetings/{body['meeting_id']}").json()
    assert detail["bot_status"] == "joining"
    assert detail["live_mom_status"] == "not_started"


# --------------------------------------------------------------------------- #
# Status webhook
# --------------------------------------------------------------------------- #
def test_status_webhook_joined_sets_live(client, mock_recall):
    body = _create_meeting(client)
    r = client.post(
        "/api/meeting-bot/webhooks/recall",
        json={"id": "evt-1", "event": "bot.status_change",
              "data": {"bot": {"id": "bot-123"}, "status": {"code": "in_call_recording"}}},
    )
    assert r.status_code == 200
    detail = client.get(f"/api/meeting-bot/meetings/{body['meeting_id']}").json()
    assert detail["status"] == "live"
    assert detail["bot_status"] == "joined"
    assert detail["audio_recording_status"] == "recording"
    assert detail["video_recording_status"] == "recording"


def test_status_webhook_done_triggers_finalize(client, mock_recall, monkeypatch):
    called = {}

    async def _finalize(meeting_id, db):
        called["meeting_id"] = meeting_id

    monkeypatch.setattr(mb_processing, "finalize_meeting", _finalize)
    body = _create_meeting(client)
    r = client.post(
        "/api/meeting-bot/webhooks/recall",
        json={"id": "evt-done", "event": "bot.done",
              "data": {"bot": {"id": "bot-123"}, "status": {"code": "done"}}},
    )
    assert r.status_code == 200
    assert called.get("meeting_id") == body["meeting_id"]


def test_status_webhook_duplicate_ignored(client, mock_recall):
    _create_meeting(client)
    payload = {"id": "evt-dup", "event": "bot.status_change",
               "data": {"bot": {"id": "bot-123"}, "status": {"code": "in_waiting_room"}}}
    first = client.post("/api/meeting-bot/webhooks/recall", json=payload).json()
    second = client.post("/api/meeting-bot/webhooks/recall", json=payload).json()
    assert first.get("duplicate") is not True
    assert second.get("duplicate") is True


# --------------------------------------------------------------------------- #
# Live transcript webhook + read
# --------------------------------------------------------------------------- #
def test_transcript_webhook_saves_and_reads(client, mock_recall):
    body = _create_meeting(client)
    payload = {
        "event": "transcript.data",
        "data": {"bot": {"id": "bot-123"}, "data": {
            "participant": {"name": "Adarsh"},
            "words": [
                {"text": "Today", "start_timestamp": {"relative": 65.0}, "end_timestamp": {"relative": 65.4}},
                {"text": "we", "start_timestamp": {"relative": 65.4}, "end_timestamp": {"relative": 65.6}},
                {"text": "test", "start_timestamp": {"relative": 65.6}, "end_timestamp": {"relative": 66.0}},
            ],
        }},
    }
    r = client.post("/api/meeting-bot/webhooks/recall/transcript", json=payload)
    assert r.status_code == 200

    tr = client.get(f"/api/meeting-bot/meetings/{body['meeting_id']}/transcripts/live").json()
    assert tr["total"] == 1
    assert tr["chunks"][0]["speaker_name"] == "Adarsh"
    assert "Today we test" in tr["chunks"][0]["text"]
    assert tr["status"] == "generating"


# --------------------------------------------------------------------------- #
# Job guards
# --------------------------------------------------------------------------- #
def test_audio_mom_requires_transcript(client, mock_recall):
    body = _create_meeting(client)
    r = client.post(f"/api/meeting-bot/meetings/{body['meeting_id']}/audio/generate-mom")
    assert r.status_code == 400


def test_audio_transcribe_trigger(client, mock_recall, monkeypatch, test_db):
    async def _run(meeting_id, source, db):
        return None

    monkeypatch.setattr(mb_processing, "run_media_transcription", _run)
    body = _create_meeting(client)
    mid = body["meeting_id"]
    # Mark completed + audio uploaded so the action is allowed.
    from app.meeting_bot.repository import MeetingBotRepository

    import asyncio
    asyncio.get_event_loop().run_until_complete(
        MeetingBotRepository(test_db).update_meeting(
            mid, {"status": "completed", "audio_recording_status": "uploaded"}
        )
    )
    r = client.post(f"/api/meeting-bot/meetings/{mid}/audio/transcribe")
    assert r.status_code == 202
    assert r.json()["status"] in ("started", "already_running")


# --------------------------------------------------------------------------- #
# Recordings endpoint
# --------------------------------------------------------------------------- #
def test_recordings_endpoint(client, mock_recall):
    body = _create_meeting(client)
    r = client.get(f"/api/meeting-bot/meetings/{body['meeting_id']}/recordings")
    assert r.status_code == 200
    data = r.json()
    assert data["audio_recording_status"] == "not_started"


# --------------------------------------------------------------------------- #
# MoM service (fake LLM) — rich schema
# --------------------------------------------------------------------------- #
class _FakeLLM:
    async def complete_json(self, system, user, temperature=0.2):
        return {
            "summary": "Discussed chatbot testing.",
            "key_discussion_points": ["chatbot", "recordings"],
            "decisions_taken": ["ship Friday"],
            "action_items": [{"task": "check audio", "owner": "Aashu", "priority": "high"}],
            "pending_tasks": ["review MoM"],
            "next_steps": ["demo"],
            "speaker_wise_notes": {"Adarsh": ["intro"]},
        }


@pytest.mark.asyncio
async def test_mom_service_rich_shape():
    mom = await MomService(llm=_FakeLLM()).generate("[00:01] Adarsh: hello")
    assert mom["summary"]
    assert mom["action_items"][0]["owner"] == "Aashu"
    assert mom["action_items"][0]["source_sentence"] is None  # normalised key present


@pytest.mark.asyncio
async def test_mom_empty_transcript_no_hallucination():
    mom = await MomService(llm=_FakeLLM()).generate("   ")
    assert mom["summary"] == ""
    assert mom["action_items"] == []


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
def test_parse_transcript_event():
    chunk = MeetingBotRecall.parse_transcript_event({
        "event": "transcript.data",
        "data": {"bot": {"id": "b1"}, "data": {
            "participant": {"name": "Bhumika"},
            "words": [{"text": "Hi", "start_timestamp": {"relative": 1.0}, "end_timestamp": {"relative": 1.2}}],
        }},
    })
    assert chunk["speaker_name"] == "Bhumika"
    assert chunk["text"] == "Hi"
    assert chunk["is_final"] is True


def test_parse_status_event():
    ev = MeetingBotRecall.parse_status_event({
        "id": "x", "event": "bot.status_change",
        "data": {"bot": {"id": "b1"}, "status": {"code": "done"}},
    })
    assert ev["bot_id"] == "b1"
    assert ev["status_code"] == "done"


def test_segments_to_chunks():
    chunks = segments_to_chunks(
        [{"start": 0.0, "end": 1.0, "text": "hello", "speaker_label": "Speaker 1"},
         {"start": 1.0, "end": 2.0, "text": "", "speaker_label": "Speaker 1"}],
        "m1", "b1", Source.AUDIO,
    )
    assert len(chunks) == 1  # empty segment dropped
    assert chunks[0]["source"] == "audio"
    assert chunks[0]["speaker_name"] == "Speaker 1"


def test_chunk_text_by_chars():
    text = "x" * 9000
    chunks = chunk_text_by_chars(text, max_chars=4000, overlap=200)
    assert len(chunks) >= 2
    assert chunk_text_by_chars("") == []


def test_friendly_speaker():
    assert friendly_speaker("SPEAKER_00") == "Speaker 1"
    assert friendly_speaker("Bhumika Girhare") == "Bhumika Girhare"
    assert friendly_speaker(None) == "Unknown"


# --------------------------------------------------------------------------- #
# Embeddings + Ask
# --------------------------------------------------------------------------- #
def test_rag_rank_orders_by_cosine():
    from app.meeting_bot.rag_service import _rank

    chunks = [
        {"text": "a", "embedding": [1.0, 0.0]},
        {"text": "b", "embedding": [0.0, 1.0]},
        {"text": "c", "embedding": [0.9, 0.1]},
    ]
    ranked = _rank([1.0, 0.0], chunks)
    assert ranked[0][0]["text"] == "a"  # most similar to the query
    assert ranked[-1][0]["text"] == "b"  # least similar


def test_embeddings_endpoint_starts(client, mock_recall):
    body = _create_meeting(client)
    r = client.post(f"/api/meeting-bot/meetings/{body['meeting_id']}/embeddings")
    assert r.status_code == 202
    assert r.json()["job"] == "embeddings"


def test_ask_without_embeddings(client, mock_recall):
    body = _create_meeting(client)
    r = client.post(
        f"/api/meeting-bot/meetings/{body['meeting_id']}/ask",
        json={"question": "what happened?"},
    )
    assert r.status_code == 200
    # No embeddings yet -> guidance, not a crash.
    assert "embeddings" in r.json()["answer"].lower()
