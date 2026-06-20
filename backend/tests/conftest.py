"""Shared test fixtures.

Uses ``mongomock_motor`` for an in-memory async Mongo, and patches the app's
Mongo lifecycle so no real database is required. External services (Recall,
OpenAI, WhisperX, pyannote, S3) are mocked per-test.
"""
from __future__ import annotations

import asyncio

import mongomock_motor
import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.db import mongo as mongo_module


@pytest.fixture
def test_db():
    client = mongomock_motor.AsyncMongoMockClient()
    db = client["meeting_bot_test"]
    mongo_module._mongo.client = client
    mongo_module._mongo.db = db
    yield db
    mongo_module._mongo.client = None
    mongo_module._mongo.db = None


@pytest.fixture
def client(test_db, monkeypatch):
    async def _noop():
        return None

    # Skip real Mongo connection during app lifespan.
    monkeypatch.setattr(main_module, "connect_to_mongo", _noop)
    monkeypatch.setattr(main_module, "close_mongo_connection", _noop)
    # Don't start the background Recall poller in tests (avoids real network calls).
    monkeypatch.setattr(main_module.poller, "start", lambda: None)
    with TestClient(main_module.app) as c:
        yield c


@pytest.fixture
def anyio_backend():
    return "asyncio"


def run(coro):
    """Helper to run a coroutine in a sync test."""
    return asyncio.get_event_loop().run_until_complete(coro)
