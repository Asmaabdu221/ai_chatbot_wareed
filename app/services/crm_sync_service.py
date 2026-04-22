from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Lead
from app.db.session import SessionLocal
from app.services.crm import get_crm_provider

logger = logging.getLogger(__name__)

_CRM_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="crm-sync")


def build_crm_payload(lead: Lead) -> Dict[str, Any]:
    return {
        "lead_id": str(lead.id),
        "conversation_id": str(lead.conversation_id),
        "phone": lead.phone,
        "latest_intent": lead.latest_intent,
        "latest_action": lead.latest_action,
        "summary_hint": lead.summary_hint,
        "source": lead.source,
        "created_at": lead.created_at.isoformat() if lead.created_at else None,
    }


def sync_lead_to_crm(lead_id: UUID, db: Session, *, is_retry: bool = False) -> Dict[str, Any]:
    lead: Optional[Lead] = db.get(Lead, lead_id)
    if lead is None:
        return {"ok": False, "reason": "lead_not_found"}
    if lead.crm_status == "synced":
        return {"ok": True, "status": "synced", "reason": "already_synced"}

    lead.crm_provider = (settings.CRM_PROVIDER or "dummy").strip().lower()
    lead.crm_last_attempt_at = datetime.now(timezone.utc)
    if is_retry:
        lead.crm_retry_count = int(lead.crm_retry_count or 0) + 1

    if not settings.CRM_SYNC_ENABLED:
        lead.crm_status = "disabled"
        lead.crm_error_message = None
        db.commit()
        _emit_lead_updated(lead)
        return {"ok": True, "status": lead.crm_status}

    provider = get_crm_provider()
    payload = build_crm_payload(lead)
    result = provider.sync_lead(payload)

    if result.ok:
        lead.crm_status = "synced"
        lead.crm_external_id = result.external_id
        lead.crm_error_message = None
        db.commit()
        _emit_lead_updated(lead)
        logger.info(
            "crm_sync | success | lead_id=%s | provider=%s | external_id=%s",
            lead.id,
            lead.crm_provider,
            lead.crm_external_id,
        )
        return {"ok": True, "status": "synced"}

    lead.crm_status = "failed"
    retry_count = int(lead.crm_retry_count or 0)
    base_error = (result.error_message or "Unknown CRM sync error").strip()
    lead.crm_error_message = (
        f"provider={lead.crm_provider} | retry_count={retry_count} | error={base_error}"
    )[:1000]
    db.commit()
    _emit_lead_updated(lead)
    logger.warning(
        "crm_sync | failed | lead_id=%s | provider=%s | error=%s",
        lead.id,
        lead.crm_provider,
        lead.crm_error_message,
    )
    return {"ok": False, "status": "failed", "error": lead.crm_error_message}


def trigger_crm_sync_for_lead(lead_id: UUID) -> None:
    if SessionLocal is None:
        return
    try:
        _CRM_EXECUTOR.submit(_sync_in_background, lead_id)
    except Exception as exc:
        logger.warning("crm_sync | trigger_failed | lead_id=%s | error=%s", lead_id, exc)


def retry_crm_sync(lead_id: UUID, db: Session) -> Dict[str, Any]:
    lead: Optional[Lead] = db.get(Lead, lead_id)
    if lead is None:
        return {"ok": False, "reason": "lead_not_found"}
    if lead.crm_status != "failed":
        return {"ok": False, "reason": "lead_not_failed"}
    if int(lead.crm_retry_count or 0) >= int(settings.CRM_SYNC_MAX_RETRIES):
        return {"ok": False, "reason": "max_retries_reached"}
    return sync_lead_to_crm(lead_id, db, is_retry=True)


def compute_retry_backoff_seconds(retry_count: int) -> int:
    base = max(1, int(settings.CRM_RETRY_BASE_DELAY_SECONDS))
    attempts = max(0, int(retry_count))
    return base * (2 ** attempts)


def is_retry_eligible(lead: Lead, *, now: Optional[datetime] = None) -> bool:
    if lead is None:
        return False
    if lead.crm_status != "failed":
        return False
    if int(lead.crm_retry_count or 0) >= int(settings.CRM_SYNC_MAX_RETRIES):
        return False

    now = now or datetime.now(timezone.utc)
    if lead.crm_last_attempt_at is None:
        return True

    last_attempt = lead.crm_last_attempt_at
    if last_attempt.tzinfo is None:
        last_attempt = last_attempt.replace(tzinfo=timezone.utc)
    wait_seconds = compute_retry_backoff_seconds(int(lead.crm_retry_count or 0))
    elapsed = (now - last_attempt).total_seconds()
    return elapsed >= wait_seconds


def get_retryable_failed_lead_ids(
    db: Session, *, now: Optional[datetime] = None, limit: Optional[int] = None
) -> list[UUID]:
    now = now or datetime.now(timezone.utc)
    batch_limit = int(limit or settings.CRM_RETRY_BATCH_SIZE)
    candidates = (
        db.query(Lead)
        .filter(Lead.crm_status == "failed")
        .order_by(Lead.crm_last_attempt_at.asc().nullsfirst(), Lead.created_at.asc())
        .limit(batch_limit)
        .all()
    )
    return [lead.id for lead in candidates if is_retry_eligible(lead, now=now)]


def _sync_in_background(lead_id: UUID) -> None:
    if SessionLocal is None:
        return
    db = SessionLocal()
    try:
        sync_lead_to_crm(lead_id, db, is_retry=False)
    except Exception as exc:
        logger.warning("crm_sync | background_error | lead_id=%s | error=%s", lead_id, exc)
    finally:
        db.close()


def _emit_lead_updated(lead: Lead) -> None:
    try:
        from app.services.lead_events import build_lead_event, lead_event_bus
        lead_event_bus.broadcast_sync(build_lead_event("lead.updated", lead))
    except Exception:
        pass
