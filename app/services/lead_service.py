"""
Lead Service — Phase 3 persistence layer for captured leads.

Public interface
---------------
  create_lead_from_draft(draft, db)
      Persist a LeadDraft to the DB.  Returns the Lead row, or None if the
      lead already exists for this conversation + phone pair (anti-duplication).

  build_lead_payload(lead)
      Serialise a Lead to a JSON-safe dict for webhook delivery.

  mark_lead_delivered(lead_id, db)
      Set status=delivered and record delivered_at timestamp.

  mark_lead_failed(lead_id, error, db)
      Set status=failed and store the error message.

  deliver_lead(lead, db)
      Best-effort delivery: POST to webhook if configured, otherwise log.
      Updates status in-place.  Never raises — all errors are caught and logged.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.db.models import Lead, LeadStatus
from app.services.conversation_state import LeadDraft

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public: create
# ---------------------------------------------------------------------------

def create_lead_from_draft(
    draft: LeadDraft,
    db: Session,
) -> Optional[Lead]:
    """
    Persist a LeadDraft.  Returns None (and logs) if a non-failed lead already
    exists for the same conversation_id + phone — prevents duplicates on retries.
    """
    if db is None:
        logger.warning("lead_service | create skipped: no DB session (demo mode)")
        return None

    conv_id = _parse_uuid(draft.conversation_id)
    if conv_id is None:
        logger.warning("lead_service | create skipped: invalid conversation_id=%r", draft.conversation_id)
        return None

    # Anti-duplication: skip if a live lead for this conversation+phone already exists
    existing = (
        db.query(Lead)
        .filter(
            Lead.conversation_id == conv_id,
            Lead.phone == draft.phone,
            Lead.status.in_([LeadStatus.NEW, LeadStatus.DELIVERED]),
        )
        .first()
    )
    if existing:
        logger.info(
            "lead_service | duplicate_skipped | lead_id=%s | conversation_id=%.8s | phone=%s",
            existing.id,
            str(conv_id),
            draft.phone,
        )
        return existing

    lead = Lead(
        conversation_id=conv_id,
        phone=draft.phone,
        latest_intent=draft.latest_intent or "",
        latest_action=draft.latest_intent or "",
        summary_hint=(draft.summary_hint or "")[:500],
        source="chatbot",
        status=LeadStatus.NEW,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    logger.info(
        "lead_service | created | lead_id=%s | conversation_id=%.8s | phone=%s | intent=%s",
        lead.id,
        str(conv_id),
        lead.phone,
        lead.latest_intent,
    )
    _emit("lead.created", lead)
    return lead


# ---------------------------------------------------------------------------
# Public: payload builder
# ---------------------------------------------------------------------------

def build_lead_payload(lead: Lead) -> dict:
    """Return a JSON-serialisable dict representing the lead for delivery."""
    return {
        "id": str(lead.id),
        "conversation_id": str(lead.conversation_id),
        "phone": lead.phone,
        "latest_intent": lead.latest_intent,
        "latest_action": lead.latest_action,
        "summary_hint": lead.summary_hint,
        "source": lead.source,
        "status": lead.status.value if hasattr(lead.status, "value") else str(lead.status),
        "created_at": lead.created_at.isoformat() if lead.created_at else None,
    }


# ---------------------------------------------------------------------------
# Public: status updates
# ---------------------------------------------------------------------------

def mark_lead_delivered(lead_id: uuid.UUID, db: Session) -> None:
    lead = db.get(Lead, lead_id)
    if lead is None:
        return
    lead.status = LeadStatus.DELIVERED
    lead.delivered_at = datetime.now(timezone.utc)
    lead.delivery_error = None
    db.commit()
    logger.info("lead_service | delivered | lead_id=%s", lead_id)
    _emit("lead.updated", lead)


def mark_lead_failed(lead_id: uuid.UUID, error: str, db: Session) -> None:
    lead = db.get(Lead, lead_id)
    if lead is None:
        return
    lead.status = LeadStatus.FAILED
    lead.delivery_error = error[:1000]
    db.commit()
    logger.warning("lead_service | failed | lead_id=%s | error=%s", lead_id, error[:200])
    _emit("lead.delivery_failed", lead)


# ---------------------------------------------------------------------------
# Public: delivery
# ---------------------------------------------------------------------------

def deliver_lead(lead: Lead, db: Session) -> None:
    """
    Deliver a lead via webhook POST or log-only stub.
    Updates lead status.  Never raises.
    """
    from app.core.config import settings

    webhook_url = (settings.INTERNAL_LEADS_WEBHOOK_URL or "").strip()
    payload = build_lead_payload(lead)

    if not webhook_url:
        _stub_delivery(lead, payload)
        # Mark as delivered even in stub mode so the lead is tracked
        if db is not None:
            try:
                mark_lead_delivered(lead.id, db)
            except Exception as _stub_mark_err:
                logger.debug("lead_service | stub mark_delivered skipped: %s", _stub_mark_err)
        return

    try:
        import httpx
        timeout = float(settings.INTERNAL_LEADS_WEBHOOK_TIMEOUT_SECONDS)
        response = httpx.post(webhook_url, json=payload, timeout=timeout)
        response.raise_for_status()
        mark_lead_delivered(lead.id, db)
        logger.info(
            "lead_service | webhook_ok | lead_id=%s | status_code=%s | url=%s",
            lead.id,
            response.status_code,
            webhook_url,
        )
    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        mark_lead_failed(lead.id, error_msg, db)
        logger.error(
            "lead_service | webhook_error | lead_id=%s | error=%s",
            lead.id,
            error_msg,
        )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _stub_delivery(lead: Lead, payload: dict) -> None:
    """Log + simulate webhook delivery when no webhook is configured.

    Marks the lead as DELIVERED so downstream systems see it as handled.
    Prints the full JSON payload to stdout for observability / future integration.
    """
    logger.info(
        "lead_service | stub_delivery | lead_id=%s | payload=%s",
        lead.id,
        json.dumps(payload, ensure_ascii=False),
    )
    # Simulate webhook POST output
    print(
        "\n📦 [LEAD WEBHOOK SIMULATION]\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
        + "\n"
    )


def _parse_uuid(value: str) -> Optional[uuid.UUID]:
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError):
        return None


def _emit(event_type: str, lead) -> None:
    """Fire-and-forget realtime event. Never raises."""
    try:
        from app.services.lead_events import lead_event_bus, build_lead_event
        lead_event_bus.broadcast_sync(build_lead_event(event_type, lead))
    except Exception as exc:
        logger.debug("lead_events | emit skipped: %s", exc)
