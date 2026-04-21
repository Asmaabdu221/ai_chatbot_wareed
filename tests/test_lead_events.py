"""
Tests for the lead realtime event system.

Coverage:
  1. build_lead_event — payload structure and field values
  2. LeadEventBus — subscribe / broadcast / unsubscribe (asyncio)
  3. broadcast_sync when no loop registered — silent no-op
  4. broadcast_sync when no subscribers — silent no-op
  5. QueueFull — overflow events are dropped without raising
  6. Event emission in create_lead_from_draft (via monkeypatch)
  7. Event emission in mark_lead_failed (via monkeypatch)
  8. Event emission in close_lead route (via monkeypatch)
  9. Dashboard-level: duplicate lead_id handled by merge (not insert)
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services.lead_events import LeadEventBus, build_lead_event, lead_event_bus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_mock_lead(
    status="new",
    phone="0501234567",
    intent="ask_phone",
    summary="أريد حجز",
    delivery_error=None,
    delivered_at=None,
):
    """Minimal Lead-shaped namespace for unit tests (no DB needed)."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        phone=phone,
        status=SimpleNamespace(value=status),
        latest_intent=intent,
        latest_action=intent,
        summary_hint=summary,
        source="chatbot",
        created_at=datetime(2026, 4, 20, 12, 0, 0, tzinfo=timezone.utc),
        delivered_at=delivered_at,
        delivery_error=delivery_error,
    )


# ---------------------------------------------------------------------------
# 1. build_lead_event — payload structure
# ---------------------------------------------------------------------------

class TestBuildLeadEvent:
    def test_contains_all_required_fields(self):
        lead = _make_mock_lead()
        payload = build_lead_event("lead.created", lead)
        required = {
            "event_type", "lead_id", "conversation_id",
            "status", "phone", "latest_intent", "latest_action",
            "summary_hint", "source", "created_at",
            "delivered_at", "delivery_error",
        }
        assert required.issubset(payload.keys())

    def test_event_type_is_preserved(self):
        lead = _make_mock_lead()
        for event_type in ("lead.created", "lead.updated", "lead.delivery_failed", "lead.closed"):
            assert build_lead_event(event_type, lead)["event_type"] == event_type

    def test_lead_id_is_string(self):
        lead = _make_mock_lead()
        payload = build_lead_event("lead.created", lead)
        assert isinstance(payload["lead_id"], str)
        uuid.UUID(payload["lead_id"])  # must be valid UUID string

    def test_status_uses_enum_value(self):
        lead = _make_mock_lead(status="delivered")
        payload = build_lead_event("lead.updated", lead)
        assert payload["status"] == "delivered"

    def test_phone_is_preserved(self):
        lead = _make_mock_lead(phone="0509876543")
        assert build_lead_event("lead.created", lead)["phone"] == "0509876543"

    def test_created_at_is_iso_string(self):
        lead = _make_mock_lead()
        payload = build_lead_event("lead.created", lead)
        assert isinstance(payload["created_at"], str)
        assert "2026" in payload["created_at"]

    def test_delivered_at_none_when_not_set(self):
        lead = _make_mock_lead(delivered_at=None)
        assert build_lead_event("lead.created", lead)["delivered_at"] is None

    def test_delivery_error_propagated(self):
        lead = _make_mock_lead(delivery_error="Connection refused")
        assert build_lead_event("lead.delivery_failed", lead)["delivery_error"] == "Connection refused"

    def test_payload_is_json_serialisable(self):
        import json
        lead = _make_mock_lead()
        payload = build_lead_event("lead.created", lead)
        dumped = json.dumps(payload)  # must not raise
        assert "lead.created" in dumped


# ---------------------------------------------------------------------------
# 2. LeadEventBus — async pub/sub
# ---------------------------------------------------------------------------

class TestLeadEventBus:
    def test_subscribe_returns_queue(self):
        bus = LeadEventBus()
        q = bus.subscribe()
        assert hasattr(q, "get_nowait")
        bus.unsubscribe(q)

    def test_subscriber_count_increments(self):
        bus = LeadEventBus()
        assert bus.subscriber_count == 0
        q = bus.subscribe()
        assert bus.subscriber_count == 1
        bus.unsubscribe(q)
        assert bus.subscriber_count == 0

    def test_broadcast_delivers_to_subscriber(self):
        bus = LeadEventBus()

        async def _run():
            loop = asyncio.get_running_loop()
            bus.set_event_loop(loop)
            q = bus.subscribe()
            event = {"event_type": "lead.created", "lead_id": "abc"}
            await bus.broadcast(event)
            received = q.get_nowait()
            assert received["event_type"] == "lead.created"
            bus.unsubscribe(q)

        asyncio.run(_run())

    def test_broadcast_delivers_to_multiple_subscribers(self):
        bus = LeadEventBus()

        async def _run():
            loop = asyncio.get_running_loop()
            bus.set_event_loop(loop)
            q1 = bus.subscribe()
            q2 = bus.subscribe()
            await bus.broadcast({"event_type": "lead.closed"})
            assert q1.get_nowait()["event_type"] == "lead.closed"
            assert q2.get_nowait()["event_type"] == "lead.closed"
            bus.unsubscribe(q1)
            bus.unsubscribe(q2)

        asyncio.run(_run())

    def test_unsubscribe_stops_delivery(self):
        bus = LeadEventBus()

        async def _run():
            loop = asyncio.get_running_loop()
            bus.set_event_loop(loop)
            q = bus.subscribe()
            bus.unsubscribe(q)
            await bus.broadcast({"event_type": "lead.created"})
            assert q.empty()

        asyncio.run(_run())

    def test_double_unsubscribe_is_safe(self):
        bus = LeadEventBus()
        q = bus.subscribe()
        bus.unsubscribe(q)
        bus.unsubscribe(q)  # must not raise


# ---------------------------------------------------------------------------
# 3. broadcast_sync — no loop / no subscribers
# ---------------------------------------------------------------------------

class TestBroadcastSync:
    def test_no_loop_registered_is_noop(self):
        bus = LeadEventBus()  # fresh bus, no loop set
        q = bus.subscribe()
        bus.broadcast_sync({"event_type": "lead.created"})  # must not raise
        assert q.empty()
        bus.unsubscribe(q)

    def test_no_subscribers_is_noop(self):
        bus = LeadEventBus()
        bus.broadcast_sync({"event_type": "lead.created"})  # must not raise

    def test_loop_not_running_is_noop(self):
        bus = LeadEventBus()
        import asyncio as _asyncio
        loop = _asyncio.new_event_loop()
        bus.set_event_loop(loop)
        # Loop is not running → broadcast_sync should not raise
        q = bus.subscribe()
        bus.broadcast_sync({"event_type": "lead.created"})
        assert q.empty()
        loop.close()
        bus.unsubscribe(q)


# ---------------------------------------------------------------------------
# 4. QueueFull — overflow drops without raising
# ---------------------------------------------------------------------------

def test_queue_full_drops_silently():
    async def _run():
        bus = LeadEventBus()
        loop = asyncio.get_running_loop()
        bus.set_event_loop(loop)
        q = bus.subscribe()
        # Fill the queue beyond maxsize
        for _ in range(q.maxsize + 5):
            await bus.broadcast({"event_type": "ping"})
        assert q.full()
        bus.unsubscribe(q)

    asyncio.run(_run())  # must not raise


# ---------------------------------------------------------------------------
# 5. Event emission in lead_service.create_lead_from_draft
# ---------------------------------------------------------------------------

class TestEmitOnCreate:
    def test_created_event_emitted(self, db):
        """lead.created is broadcast after successful DB persist."""
        from app.services.lead_service import create_lead_from_draft
        from app.services.conversation_state import LeadDraft

        emitted = []

        with patch("app.services.lead_service._emit") as mock_emit:
            draft = LeadDraft(
                phone="0501111111",
                conversation_id=str(uuid.uuid4()),
                latest_intent="ask_phone",
                summary_hint="test",
            )
            lead = create_lead_from_draft(draft, db)
            assert lead is not None
            mock_emit.assert_called_once_with("lead.created", lead)

    def test_no_emit_when_duplicate(self, db):
        """No event emitted when create_lead_from_draft skips a duplicate."""
        from app.services.lead_service import create_lead_from_draft
        from app.services.conversation_state import LeadDraft

        cid = str(uuid.uuid4())
        draft = LeadDraft(phone="0502222222", conversation_id=cid, latest_intent="ask_phone", summary_hint="")

        with patch("app.services.lead_service._emit") as mock_emit:
            create_lead_from_draft(draft, db)   # first — emits
            mock_emit.reset_mock()
            create_lead_from_draft(draft, db)   # duplicate — no emit
            mock_emit.assert_not_called()


# ---------------------------------------------------------------------------
# 6. Event emission in lead_service.mark_lead_failed
# ---------------------------------------------------------------------------

def test_emit_on_mark_failed(db):
    from app.services.lead_service import create_lead_from_draft, mark_lead_failed
    from app.services.conversation_state import LeadDraft

    draft = LeadDraft(
        phone="0503333333",
        conversation_id=str(uuid.uuid4()),
        latest_intent="ask_phone",
        summary_hint="",
    )
    lead = create_lead_from_draft(draft, db)
    assert lead is not None

    with patch("app.services.lead_service._emit") as mock_emit:
        mark_lead_failed(lead.id, "timeout", db)
        mock_emit.assert_called_once_with("lead.delivery_failed", lead)


# ---------------------------------------------------------------------------
# 7. Event emission in close_lead route
# ---------------------------------------------------------------------------

def test_emit_on_close_lead(db):
    """POST /{id}/close emits lead.closed via broadcast_sync."""
    from app.services.lead_service import create_lead_from_draft
    from app.services.conversation_state import LeadDraft

    draft = LeadDraft(
        phone="0504444444",
        conversation_id=str(uuid.uuid4()),
        latest_intent="ask_phone",
        summary_hint="",
    )
    lead = create_lead_from_draft(draft, db)
    assert lead is not None

    with patch("app.services.lead_events.lead_event_bus") as mock_bus:
        mock_bus.broadcast_sync = MagicMock()
        from app.api.internal_leads import close_lead
        result = close_lead(lead.id, db)
        assert result.status == "closed"
        mock_bus.broadcast_sync.assert_called_once()
        call_args = mock_bus.broadcast_sync.call_args[0][0]
        assert call_args["event_type"] == "lead.closed"
        assert call_args["lead_id"] == str(lead.id)


# ---------------------------------------------------------------------------
# 8. Duplicate merge safety (unit test — no DOM, pure data logic)
# ---------------------------------------------------------------------------

def test_upsert_logic_no_duplicates():
    """
    The frontend merges SSE events by lead_id.  Verify the upsert logic:
    - existing lead → updated in place (no new entry)
    - new lead_id   → prepended
    """
    lead_id = str(uuid.uuid4())
    leads = [
        {"id": lead_id, "phone": "0501234567", "status": "new"},
        {"id": str(uuid.uuid4()), "phone": "0507654321", "status": "delivered"},
    ]

    # Simulate the JS upsert: update existing
    incoming = {"id": lead_id, "status": "closed"}
    idx = next((i for i, l in enumerate(leads) if l["id"] == incoming["id"]), -1)
    if idx >= 0:
        leads[idx] = {**leads[idx], **incoming}
    else:
        leads = [incoming] + leads

    assert len(leads) == 2  # no duplicate
    assert leads[0]["status"] == "closed"

    # Simulate: new lead
    new_lead = {"id": str(uuid.uuid4()), "phone": "0509999999", "status": "new"}
    idx = next((i for i, l in enumerate(leads) if l["id"] == new_lead["id"]), -1)
    if idx >= 0:
        leads[idx] = {**leads[idx], **new_lead}
    else:
        leads = [new_lead] + leads

    assert len(leads) == 3
    assert leads[0]["id"] == new_lead["id"]  # prepended


# ---------------------------------------------------------------------------
# 9. Realtime failure does not prevent REST fallback (smoke test)
# ---------------------------------------------------------------------------

def test_fetch_leads_works_without_sse(db):
    """
    The REST endpoint must work regardless of SSE status.
    Create a lead, fetch via list_leads — must return it.
    """
    from app.services.lead_service import create_lead_from_draft
    from app.services.conversation_state import LeadDraft
    from app.api.internal_leads import list_leads

    draft = LeadDraft(
        phone="0505555555",
        conversation_id=str(uuid.uuid4()),
        latest_intent="ask_phone",
        summary_hint="fallback test",
    )
    with patch("app.services.lead_service._emit"):  # suppress SSE in this test
        lead = create_lead_from_draft(draft, db)
    assert lead is not None

    result = list_leads(status_filter=None, page=1, page_size=100, db=db)
    assert result.total >= 1
    phones = [item.phone for item in result.items]
    assert "0505555555" in phones
