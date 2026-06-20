"""Tests for the Recall.ai integration service using a mocked HTTP transport."""
import httpx
import pytest

from app.services.recall_service import RecallService


@pytest.mark.asyncio
async def test_create_bot_posts_and_returns_id():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.content.decode()
        return httpx.Response(201, json={"id": "bot_123", "status": "scheduled"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        recall = RecallService(api_key="test-key", client=http)
        bot = await recall.create_bot("https://zoom.us/j/123", bot_name="QA Bot")

    assert bot["id"] == "bot_123"
    assert "/bot" in captured["url"]
    assert "zoom.us" in captured["body"]


@pytest.mark.asyncio
async def test_get_recording_url_extracts_download_url():
    bot_payload = {
        "id": "bot_123",
        "recordings": [
            {
                "media_shortcuts": {
                    "video_mixed": {"data": {"download_url": "https://cdn/rec.mp4"}}
                }
            }
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=bot_payload)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        recall = RecallService(api_key="test-key", client=http)
        url = await recall.get_recording_url("bot_123")

    assert url == "https://cdn/rec.mp4"


def test_verify_webhook_skips_when_no_secret(monkeypatch):
    from app.services.recall_service import settings

    monkeypatch.setattr(settings, "recall_webhook_secret", None)
    assert RecallService.verify_webhook(b"{}", None) is True


def test_verify_webhook_validates_hmac(monkeypatch):
    import hashlib
    import hmac

    from app.services.recall_service import settings

    secret = "shh"
    monkeypatch.setattr(settings, "recall_webhook_secret", secret)
    body = b'{"event":"bot.done"}'
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    assert RecallService.verify_webhook(body, f"sha256={sig}") is True
    assert RecallService.verify_webhook(body, "deadbeef") is False
