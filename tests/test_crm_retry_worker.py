from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.services.conversation_state import LeadDraft
from app.services.crm_retry_worker import process_retry_batch
from app.services.crm_sync_service import get_retryable_failed_lead_ids, is_retry_eligible
from app.services.lead_analytics_service import get_lead_analytics
from app.services.lead_service import create_lead_from_draft


def _draft(phone: str) -> LeadDraft:
    return LeadDraft(
        phone=phone,
        conversation_id=str(uuid.uuid4()),
        latest_intent="ask_phone",
        summary_hint="crm retry worker test",
    )


def test_retry_eligibility_respects_backoff_and_limits(db, monkeypatch):
    lead = create_lead_from_draft(_draft("0503333301"), db)
    assert lead is not None

    monkeypatch.setattr(settings, "CRM_SYNC_MAX_RETRIES", 3)
    monkeypatch.setattr(settings, "CRM_RETRY_BASE_DELAY_SECONDS", 30)

    now = datetime.now(timezone.utc)
    lead.crm_status = "failed"
    lead.crm_retry_count = 0
    lead.crm_last_attempt_at = now - timedelta(seconds=10)
    db.commit()
    assert is_retry_eligible(lead, now=now) is False

    lead.crm_last_attempt_at = now - timedelta(seconds=31)
    db.commit()
    assert is_retry_eligible(lead, now=now) is True

    lead.crm_status = "synced"
    db.commit()
    assert is_retry_eligible(lead, now=now) is False

    lead.crm_status = "failed"
    lead.crm_retry_count = 3
    db.commit()
    assert is_retry_eligible(lead, now=now) is False


def test_retry_worker_processes_only_eligible_failed_leads(db, sqlite_engine, monkeypatch):
    eligible = create_lead_from_draft(_draft("0503333302"), db)
    maxed = create_lead_from_draft(_draft("0503333303"), db)
    assert eligible is not None and maxed is not None

    now = datetime.now(timezone.utc)
    eligible.crm_status = "failed"
    eligible.crm_retry_count = 0
    eligible.crm_last_attempt_at = now - timedelta(minutes=5)

    maxed.crm_status = "failed"
    maxed.crm_retry_count = 2
    maxed.crm_last_attempt_at = now - timedelta(minutes=5)
    db.commit()

    monkeypatch.setattr(settings, "CRM_SYNC_ENABLED", True)
    monkeypatch.setattr(settings, "CRM_PROVIDER", "dummy")
    monkeypatch.setattr(settings, "CRM_SYNC_MAX_RETRIES", 2)
    monkeypatch.setattr(settings, "CRM_RETRY_BASE_DELAY_SECONDS", 1)
    monkeypatch.setattr(settings, "CRM_RETRY_BATCH_SIZE", 50)

    SessionLocal = sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False)
    import app.services.crm_retry_worker as worker_mod
    monkeypatch.setattr(worker_mod, "SessionLocal", SessionLocal)

    result = process_retry_batch()
    assert result["processed"] == 1
    assert result["succeeded"] == 1

    db.expire_all()
    e = db.get(type(eligible), eligible.id)
    m = db.get(type(maxed), maxed.id)
    assert e.crm_status == "synced"
    assert e.crm_retry_count == 1
    assert m.crm_status == "failed"
    assert m.crm_retry_count == 2

    ids = get_retryable_failed_lead_ids(db, now=datetime.now(timezone.utc), limit=50)
    assert maxed.id not in ids


def test_crm_analytics_rates_and_retry_distribution(db):
    l1 = create_lead_from_draft(_draft("0503333304"), db)
    l2 = create_lead_from_draft(_draft("0503333305"), db)
    assert l1 is not None and l2 is not None

    l1.crm_status = "synced"
    l1.crm_retry_count = 1
    l2.crm_status = "failed"
    l2.crm_retry_count = 2
    db.commit()

    metrics = get_lead_analytics(db)
    assert "crm_sync_success_rate" in metrics["rates"]
    assert "crm_sync_failure_rate" in metrics["rates"]
    assert metrics["rates"]["crm_sync_success_rate"] >= 0.0
    assert metrics["rates"]["crm_sync_failure_rate"] >= 0.0
    distribution = metrics.get("retry_distribution", [])
    retry_counts = {row["retry_count"] for row in distribution}
    assert 1 in retry_counts
    assert 2 in retry_counts
