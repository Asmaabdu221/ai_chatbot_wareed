"""
Lead System tests — persistence, delivery, anti-duplication, and API.

All tests use an in-memory SQLite database so no PostgreSQL instance is needed.
The Lead model uses ENUM types that must be declared natively for SQLite.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models import Lead, LeadStatus
from app.services.conversation_state import LeadDraft
from app.services.lead_service import (
    build_lead_payload,
    create_lead_from_draft,
    deliver_lead,
    mark_lead_delivered,
    mark_lead_failed,
)


# ---------------------------------------------------------------------------
# SQLite fixture — patch ENUM to use String for compatibility
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def sqlite_engine():
    engine = create_engine("sqlite:///:memory:", future=True)

    # SQLite doesn't support PostgreSQL ENUM — swap to String for tests
    from sqlalchemy import String
    from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM

    @event.listens_for(engine, "connect")
    def _connect(dbapi_conn, rec):
        pass

    # Patch LeadStatus column to use String on SQLite
    Lead.__table__.c.status.type = String(20)

    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    # Restore type after module tests complete
    from sqlalchemy import Enum as SAEnum
    Lead.__table__.c.status.type = SAEnum(
        LeadStatus,
        name="lead_status",
        create_type=False,
        values_callable=lambda x: [e.value for e in x],
    )


@pytest.fixture()
def db(sqlite_engine) -> Generator[Session, None, None]:
    SessionLocal = sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False)
    session = SessionLocal()
    yield session
    session.rollback()
    session.close()


@pytest.fixture()
def sample_draft() -> LeadDraft:
    return LeadDraft(
        phone="0501234567",
        conversation_id=str(uuid.uuid4()),
        latest_intent="ask_phone",
        summary_hint="أريد حجز تحليل",
    )


# ---------------------------------------------------------------------------
# create_lead_from_draft
# ---------------------------------------------------------------------------

def test_create_lead_persists_to_db(db, sample_draft):
    lead = create_lead_from_draft(sample_draft, db)
    assert lead is not None
    assert lead.id is not None
    assert lead.phone == sample_draft.phone
    assert lead.conversation_id == uuid.UUID(sample_draft.conversation_id)
    assert lead.latest_intent == "ask_phone"
    assert lead.source == "chatbot"
    assert lead.status == LeadStatus.NEW


def test_create_lead_status_is_new(db, sample_draft):
    lead = create_lead_from_draft(sample_draft, db)
    assert lead.status == LeadStatus.NEW


def test_create_lead_summary_hint_stored(db):
    draft = LeadDraft(
        phone="0509999999",
        conversation_id=str(uuid.uuid4()),
        latest_intent="transfer_to_human",
        summary_hint="أبي أتكلم مع خدمة العملاء",
    )
    lead = create_lead_from_draft(draft, db)
    assert lead.summary_hint == "أبي أتكلم مع خدمة العملاء"


def test_create_lead_returns_none_when_no_db(sample_draft):
    result = create_lead_from_draft(sample_draft, db=None)
    assert result is None


def test_create_lead_invalid_conversation_id(db):
    draft = LeadDraft(
        phone="0501234567",
        conversation_id="not-a-uuid",
        latest_intent="ask_phone",
        summary_hint="",
    )
    result = create_lead_from_draft(draft, db)
    assert result is None


# ---------------------------------------------------------------------------
# Anti-duplication
# ---------------------------------------------------------------------------

def test_duplicate_lead_skipped(db):
    cid = str(uuid.uuid4())
    draft = LeadDraft(
        phone="0507777777",
        conversation_id=cid,
        latest_intent="ask_phone",
        summary_hint="test",
    )
    first = create_lead_from_draft(draft, db)
    second = create_lead_from_draft(draft, db)
    assert first is not None
    assert second is not None
    assert first.id == second.id  # same row returned, not a new one


def test_failed_lead_allows_new_lead(db):
    cid = str(uuid.uuid4())
    draft = LeadDraft(
        phone="0508888888",
        conversation_id=cid,
        latest_intent="ask_phone",
        summary_hint="test",
    )
    first = create_lead_from_draft(draft, db)
    assert first is not None
    # Mark it failed
    mark_lead_failed(first.id, "webhook down", db)
    db.expire(first)

    # A new lead with same conv+phone should now be created (failed leads are re-creatable)
    # Note: current implementation checks status IN (NEW, DELIVERED) so FAILED allows new
    second = create_lead_from_draft(draft, db)
    assert second is not None
    assert second.id != first.id


# ---------------------------------------------------------------------------
# build_lead_payload
# ---------------------------------------------------------------------------

def test_build_payload_has_required_fields(db, sample_draft):
    lead = create_lead_from_draft(sample_draft, db)
    payload = build_lead_payload(lead)
    assert "id" in payload
    assert "conversation_id" in payload
    assert "phone" in payload
    assert "latest_intent" in payload
    assert "status" in payload
    assert "created_at" in payload


def test_build_payload_is_json_serialisable(db, sample_draft):
    lead = create_lead_from_draft(sample_draft, db)
    payload = build_lead_payload(lead)
    dumped = json.dumps(payload)  # must not raise
    assert sample_draft.phone in dumped


# ---------------------------------------------------------------------------
# mark_lead_delivered / mark_lead_failed
# ---------------------------------------------------------------------------

def test_mark_delivered_updates_status(db, sample_draft):
    lead = create_lead_from_draft(sample_draft, db)
    mark_lead_delivered(lead.id, db)
    db.expire(lead)
    refreshed = db.get(Lead, lead.id)
    assert refreshed.status == LeadStatus.DELIVERED
    assert refreshed.delivered_at is not None


def test_mark_failed_stores_error(db):
    draft = LeadDraft(
        phone="0502345678",
        conversation_id=str(uuid.uuid4()),
        latest_intent="ask_phone",
        summary_hint="",
    )
    lead = create_lead_from_draft(draft, db)
    mark_lead_failed(lead.id, "Connection refused", db)
    db.expire(lead)
    refreshed = db.get(Lead, lead.id)
    assert refreshed.status == LeadStatus.FAILED
    assert "Connection refused" in refreshed.delivery_error


def test_mark_delivered_nonexistent_lead_is_noop(db):
    # Should not raise
    mark_lead_delivered(uuid.uuid4(), db)


# ---------------------------------------------------------------------------
# deliver_lead — stub mode (no webhook configured)
# ---------------------------------------------------------------------------

def test_deliver_lead_stub_mode_logs_and_does_not_raise(db, sample_draft, caplog):
    lead = create_lead_from_draft(sample_draft, db)
    with patch("app.core.config.settings") as mock_settings:
        mock_settings.INTERNAL_LEADS_WEBHOOK_URL = ""
        mock_settings.INTERNAL_LEADS_WEBHOOK_TIMEOUT_SECONDS = 5
        import logging
        with caplog.at_level(logging.INFO, logger="app.services.lead_service"):
            deliver_lead(lead, db)
    # Status stays NEW in stub mode (we only log)
    db.expire(lead)
    refreshed = db.get(Lead, lead.id)
    assert refreshed.status == LeadStatus.NEW


# ---------------------------------------------------------------------------
# deliver_lead — webhook mode
# ---------------------------------------------------------------------------

def test_deliver_lead_webhook_success_marks_delivered(db):
    draft = LeadDraft(
        phone="0503456789",
        conversation_id=str(uuid.uuid4()),
        latest_intent="ask_phone",
        summary_hint="",
    )
    lead = create_lead_from_draft(draft, db)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()

    with patch("app.core.config.settings") as mock_settings, \
         patch("httpx.post", return_value=mock_response):
        mock_settings.INTERNAL_LEADS_WEBHOOK_URL = "https://example.internal/leads"
        mock_settings.INTERNAL_LEADS_WEBHOOK_TIMEOUT_SECONDS = 5
        deliver_lead(lead, db)

    db.expire(lead)
    refreshed = db.get(Lead, lead.id)
    assert refreshed.status == LeadStatus.DELIVERED
    assert refreshed.delivered_at is not None


def test_deliver_lead_webhook_failure_marks_failed(db):
    draft = LeadDraft(
        phone="0504567890",
        conversation_id=str(uuid.uuid4()),
        latest_intent="ask_phone",
        summary_hint="",
    )
    lead = create_lead_from_draft(draft, db)

    with patch("app.core.config.settings") as mock_settings, \
         patch("httpx.post", side_effect=ConnectionError("refused")):
        mock_settings.INTERNAL_LEADS_WEBHOOK_URL = "https://example.internal/leads"
        mock_settings.INTERNAL_LEADS_WEBHOOK_TIMEOUT_SECONDS = 5
        deliver_lead(lead, db)  # must not raise

    db.expire(lead)
    refreshed = db.get(Lead, lead.id)
    assert refreshed.status == LeadStatus.FAILED
    assert refreshed.delivery_error is not None


# ---------------------------------------------------------------------------
# User-facing reply is unaffected by lead creation
# ---------------------------------------------------------------------------

def test_phone_capture_reply_is_independent_of_lead_creation():
    """
    The FlowResult.final_reply must contain the confirmation message regardless
    of whether lead persistence succeeds or fails.
    """
    from app.services.conversation_state import StateEnum, get_state_store
    from app.services.conversation_flow import process_phone_submission
    from app.services.cta_templates import CONFIRM_PHONE_RECEIVED

    cid = str(uuid.uuid4())
    store = get_state_store()
    store.update(cid, state=StateEnum.AWAITING_PHONE, pending_action="ask_phone")
    state = store.get(cid)

    result = process_phone_submission("رقمي 0501234567", state, cid)
    assert result is not None
    assert result.phone_captured is True
    assert result.final_reply == CONFIRM_PHONE_RECEIVED
    assert result.lead_draft is not None
    assert result.lead_draft.phone == "0501234567"
