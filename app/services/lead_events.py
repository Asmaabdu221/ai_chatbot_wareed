"""
Lead Event Bus — thread-safe asyncio pub/sub for realtime internal lead events.

Architecture
------------
One asyncio.Queue per SSE subscriber.  Events are published by lead_service
(sync, runs in threadpool) via broadcast_sync(), which uses
run_coroutine_threadsafe() to safely cross the sync/async boundary.

The running event loop must be registered once at startup via set_event_loop().
Until that call, or when no subscribers are connected, broadcasts are silent.

Event types
-----------
  lead.created         — new lead persisted after phone capture
  lead.updated         — lead status changed to delivered
  lead.delivery_failed — webhook delivery failed
  lead.closed          — staff manually closed the lead
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

_MAX_QUEUE_SIZE = 100   # per subscriber; oldest events silently dropped when full
_SSE_PING_INTERVAL = 20  # seconds; heartbeat sent when queue is idle


class LeadEventBus:
    """Thread-safe asyncio pub/sub bus with one Queue per SSE subscriber."""

    def __init__(self) -> None:
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._queues: list[asyncio.Queue] = []
        self._lock = threading.Lock()

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Call once at app startup with the running event loop."""
        self._loop = loop
        logger.info("lead_events | event_loop_registered | loop=%r", loop)

    def subscribe(self) -> asyncio.Queue:
        """Create a new subscriber queue and register it.  Returns the queue."""
        q: asyncio.Queue = asyncio.Queue(maxsize=_MAX_QUEUE_SIZE)
        with self._lock:
            self._queues.append(q)
        logger.debug("lead_events | subscribed | total=%d", len(self._queues))
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        """Remove a subscriber queue (called in SSE generator finally block)."""
        with self._lock:
            try:
                self._queues.remove(q)
            except ValueError:
                pass
        logger.debug("lead_events | unsubscribed | total=%d", len(self._queues))

    def broadcast_sync(self, event: dict) -> None:
        """
        Publish from synchronous code running in a threadpool.
        No-op when no loop is registered or no subscribers are connected.
        """
        loop = self._loop
        if loop is None or not loop.is_running():
            return
        with self._lock:
            queues = list(self._queues)
        if not queues:
            return
        for q in queues:
            asyncio.run_coroutine_threadsafe(_put_or_drop(q, event), loop)
        logger.debug(
            "lead_events | broadcast_sync | event_type=%s | subscribers=%d",
            event.get("event_type"),
            len(queues),
        )

    async def broadcast(self, event: dict) -> None:
        """Publish from async code."""
        with self._lock:
            queues = list(self._queues)
        for q in queues:
            await _put_or_drop(q, event)
        logger.debug(
            "lead_events | broadcast | event_type=%s | subscribers=%d",
            event.get("event_type"),
            len(queues),
        )

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._queues)


async def _put_or_drop(q: asyncio.Queue, event: dict) -> None:
    try:
        q.put_nowait(event)
    except asyncio.QueueFull:
        logger.warning(
            "lead_events | queue_full | dropping event_type=%s", event.get("event_type")
        )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

lead_event_bus = LeadEventBus()


# ---------------------------------------------------------------------------
# Event payload builder
# ---------------------------------------------------------------------------

def build_lead_event(event_type: str, lead) -> dict:
    """
    Canonical SSE payload from a Lead ORM object.
    Safe to call after db.commit() because expire_on_commit=False in session factory.
    """
    def _iso(dt) -> Optional[str]:
        if dt is None:
            return None
        return dt if isinstance(dt, str) else dt.isoformat()

    status_val = lead.status.value if hasattr(lead.status, "value") else str(lead.status)

    return {
        "event_type": event_type,
        "lead_id": str(lead.id),
        "conversation_id": str(lead.conversation_id),
        "status": status_val,
        "phone": lead.phone,
        "latest_intent": lead.latest_intent,
        "latest_action": lead.latest_action,
        "summary_hint": lead.summary_hint,
        "source": lead.source,
        "created_at": _iso(lead.created_at),
        "delivered_at": _iso(getattr(lead, "delivered_at", None)),
        "delivery_error": getattr(lead, "delivery_error", None),
    }
