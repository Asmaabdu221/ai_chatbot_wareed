from __future__ import annotations

import uuid

from app.core.config import settings
from app.services.conversation_state import LeadDraft
from app.services.crm_sync_service import retry_crm_sync, sync_lead_to_crm
from app.services.lead_service import create_lead_from_draft


def _draft(phone: str) -> LeadDraft:
    return LeadDraft(
        phone=phone,
        conversation_id=str(uuid.uuid4()),
        latest_intent="ask_phone",
        summary_hint="crm sync test",
    )


def test_crm_sync_disabled_marks_lead_disabled(db, monkeypatch):
    lead = create_lead_from_draft(_draft("0501111119"), db)
    assert lead is not None

    monkeypatch.setattr(settings, "CRM_SYNC_ENABLED", False)
    monkeypatch.setattr(settings, "CRM_PROVIDER", "dummy")

    result = sync_lead_to_crm(lead.id, db)
    db.refresh(lead)

    assert result["ok"] is True
    assert lead.crm_status == "disabled"


def test_crm_sync_dummy_provider_success(db, monkeypatch):
    lead = create_lead_from_draft(_draft("0501111120"), db)
    assert lead is not None

    monkeypatch.setattr(settings, "CRM_SYNC_ENABLED", True)
    monkeypatch.setattr(settings, "CRM_PROVIDER", "dummy")

    result = sync_lead_to_crm(lead.id, db)
    db.refresh(lead)

    assert result["ok"] is True
    assert lead.crm_status == "synced"
    assert lead.crm_external_id is not None
    assert lead.crm_error_message is None


def test_crm_retry_increments_retry_count(db, monkeypatch):
    lead = create_lead_from_draft(_draft("0501111121"), db)
    assert lead is not None

    monkeypatch.setattr(settings, "CRM_SYNC_ENABLED", True)
    monkeypatch.setattr(settings, "CRM_PROVIDER", "real")
    monkeypatch.setattr(settings, "CRM_SYNC_MAX_RETRIES", 3)

    first = sync_lead_to_crm(lead.id, db)
    db.refresh(lead)
    assert first["ok"] is False
    assert lead.crm_status == "failed"
    assert lead.crm_retry_count == 0

    monkeypatch.setattr(settings, "CRM_PROVIDER", "dummy")
    retried = retry_crm_sync(lead.id, db)
    db.refresh(lead)

    assert retried["ok"] is True
    assert lead.crm_status == "synced"
    assert lead.crm_retry_count == 1
