"""In-process pub/sub for live meeting events, exposed to the frontend via SSE.

Each meeting has a set of subscriber queues. The transcript webhook (and status
updates) publish events; the SSE endpoint drains a per-connection queue. This is
single-process (matches the no-queue/no-worker constraint); for multi-worker
deployments swap the broker for Redis pub/sub behind the same interface.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)


class LiveEventBroker:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)

    async def publish(self, meeting_id: str, event_type: str, data: Any) -> None:
        payload = {"type": event_type, "data": data}
        for q in list(self._subscribers.get(meeting_id, ())):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:  # slow client — drop oldest
                pass

    async def subscribe(self, meeting_id: str) -> AsyncIterator[str]:
        """Yield SSE-formatted lines for a meeting until the client disconnects."""
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subscribers[meeting_id].add(q)
        try:
            # Initial hello so the client knows the stream is open.
            yield _sse({"type": "connected", "data": {"meeting_id": meeting_id}})
            while True:
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield _sse(payload)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"  # comment line keeps the connection alive
        finally:
            self._subscribers[meeting_id].discard(q)
            if not self._subscribers[meeting_id]:
                self._subscribers.pop(meeting_id, None)


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, default=str)}\n\n"


# Module-level singleton broker.
broker = LiveEventBroker()
