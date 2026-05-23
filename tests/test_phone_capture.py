"""
Regression tests for phone capture -> leads table (the /internal/leads bug).

Covers:
  * detect_phone normalises a Saudi mobile and rejects prices/years.
  * A captured phone is persisted to the leads table and marked DELIVERED
    (stub delivery when no webhook is configured).
"""

from __future__ import annotations

import uuid

import pytest

from app.services.phone_utils import detect_phone


def test_detect_phone_local_and_rejects_noise():
    assert detect_phone("0501234567") == "+966501234567"
    assert detect_phone("رقمي 0501234567 شكرا") == "+966501234567"
    assert detect_phone("+966501234567") == "+966501234567"
    # must NOT treat prices / years as phones
    assert detect_phone("السعر 150 ريال") is None
    assert detect_phone("2024") is None


def test_phone_text_message_creates_lead_row(db):
    """Sending '0501234567' as a text message must land in the leads table."""
    from app.services.conversation_state import LeadDraft
    from app.services.lead_service import create_lead_from_draft, deliver_lead
    from app.db.models import Lead, LeadStatus

    phone = detect_phone("0501234567")
    assert phone == "+966501234567"

    draft = LeadDraft(
        phone=phone,
        conversation_id=str(uuid.uuid4()),
        latest_intent="inbound_phone",
        summary_hint="0501234567",
        status="ready",
    )
    lead = create_lead_from_draft(draft, db)
    assert lead is not None, "lead row should be created"
    deliver_lead(lead, db)

    rows = db.query(Lead).filter(Lead.phone == phone).all()
    assert len(rows) == 1
    assert str(rows[0].status) in ("LeadStatus.DELIVERED", "delivered", str(LeadStatus.DELIVERED))


def test_duplicate_phone_not_double_inserted(db):
    from app.services.conversation_state import LeadDraft
    from app.services.lead_service import create_lead_from_draft
    from app.db.models import Lead

    conv = str(uuid.uuid4())
    phone = "+966500000001"
    d1 = LeadDraft(phone=phone, conversation_id=conv, latest_intent="inbound_phone", summary_hint="x", status="ready")
    d2 = LeadDraft(phone=phone, conversation_id=conv, latest_intent="inbound_phone", summary_hint="x", status="ready")
    create_lead_from_draft(d1, db)
    create_lead_from_draft(d2, db)
    rows = db.query(Lead).filter(Lead.conversation_id == uuid.UUID(conv), Lead.phone == phone).all()
    assert len(rows) == 1, "anti-duplication should prevent a second live lead"
