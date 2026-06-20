"""API-level tests: meeting creation, webhook handling, processing trigger.

External calls (Recall bot creation, the background pipeline) are monkeypatched
so the tests stay fast and offline.
"""
import app.routers.meetings as meetings_router
import app.routers.webhooks as webhooks_router


def _patch_recall_create(monkeypatch, bot_id="bot_abc"):
    class FakeRecall:
        def __init__(self, *a, **k):
            pass

        async def create_bot(self, **kwargs):
            return {"id": bot_id, "status": "scheduled"}

    monkeypatch.setattr(meetings_router, "RecallService", FakeRecall)


def test_create_meeting_dispatches_bot(client, monkeypatch):
    _patch_recall_create(monkeypatch)

    resp = client.post(
        "/api/meetings",
        json={"title": "Sprint Planning", "meeting_url": "https://meet.google.com/abc"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["title"] == "Sprint Planning"
    assert body["recall_bot_id"] == "bot_abc"
    assert body["status"] == "bot_scheduled"


def test_list_and_get_meeting(client, monkeypatch):
    _patch_recall_create(monkeypatch)
    created = client.post(
        "/api/meetings", json={"title": "Standup", "meeting_url": "https://zoom.us/j/1"}
    ).json()

    listed = client.get("/api/meetings").json()
    assert any(m["id"] == created["id"] for m in listed)

    fetched = client.get(f"/api/meetings/{created['id']}").json()
    assert fetched["title"] == "Standup"


def test_webhook_triggers_processing(client, monkeypatch):
    _patch_recall_create(monkeypatch, bot_id="bot_hook")
    created = client.post(
        "/api/meetings", json={"title": "Review", "meeting_url": "https://zoom.us/j/2"}
    ).json()

    called = {}

    async def fake_process(meeting_id, db):
        called["meeting_id"] = meeting_id

    monkeypatch.setattr(webhooks_router, "process_meeting", fake_process)

    resp = client.post(
        "/api/webhooks/recall",
        json={"event": "bot.done", "data": {"bot_id": "bot_hook"}},
    )
    assert resp.status_code == 200
    assert resp.json()["processing"] == created["id"]
    # BackgroundTasks run after the response is sent by TestClient.
    assert called.get("meeting_id") == created["id"]


def test_webhook_ignores_unknown_bot(client):
    resp = client.post(
        "/api/webhooks/recall",
        json={"event": "bot.done", "data": {"bot_id": "nope"}},
    )
    assert resp.status_code == 200
    assert resp.json()["ignored"] == "unknown bot"
