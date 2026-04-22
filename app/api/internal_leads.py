"""
Internal Leads API — staff/dashboard integration endpoint.

All routes require an `X-Internal-Api-Key` header matching
settings.INTERNAL_LEADS_API_KEY.  When the key is empty (dev mode)
the header check is skipped so local testing works without configuration.

Routes
------
  GET  /internal/leads              List leads (paginated, filterable by status)
  GET  /internal/leads/stream       SSE stream for realtime lead events
  GET  /internal/leads/{lead_id}    Retrieve a single lead
  POST /internal/leads/{lead_id}/close   Mark a lead as closed

Note: /stream must be declared before /{lead_id} to avoid route shadowing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import date, datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.permissions import require_internal_access, require_internal_access_sse
from app.db import get_db
from app.db.models import Lead, LeadStatus, User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/internal/leads", tags=["internal-leads"])


# ---------------------------------------------------------------------------
# Auth note
# ---------------------------------------------------------------------------
# All routes use require_internal_access (from app.core.permissions).
# That dependency accepts JWT Bearer with internal role OR X-Internal-Api-Key header.
# The SSE stream uses require_internal_access_sse which additionally accepts
# ?token= and ?api_key= query params (EventSource cannot send custom headers).
# The old _require_api_key / _check_key helpers are removed.


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class LeadOut(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    phone: str
    latest_intent: str
    latest_action: str
    summary_hint: str
    source: str
    status: str
    created_at: Optional[datetime]
    delivered_at: Optional[datetime]
    delivery_error: Optional[str]
    crm_status: Optional[str] = None
    crm_provider: Optional[str] = None
    crm_external_id: Optional[str] = None
    crm_last_attempt_at: Optional[datetime] = None
    crm_error_message: Optional[str] = None
    crm_retry_count: int = 0

    class Config:
        from_attributes = True


class LeadsListOut(BaseModel):
    items: List[LeadOut]
    total: int
    page: int
    page_size: int
    status_counts: Dict[str, int] = {}


# ---------------------------------------------------------------------------
# Date parsing helper
# ---------------------------------------------------------------------------

def _parse_date_param(value: str, param_name: str, *, end_of_day: bool = False) -> Optional[datetime]:
    """Parse YYYY-MM-DD or ISO 8601 string. Returns None for empty input. Raises 400 on invalid."""
    if not value or not value.strip():
        return None
    value = value.strip()
    try:
        if "T" in value or " " in value:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        d = date.fromisoformat(value)
        if end_of_day:
            return datetime(d.year, d.month, d.day, 23, 59, 59)
        return datetime(d.year, d.month, d.day, 0, 0, 0)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {param_name}: {value!r} — expected YYYY-MM-DD or ISO 8601",
        )


# ---------------------------------------------------------------------------
# Routes — list and SSE (declared before /{lead_id} to avoid shadowing)
# ---------------------------------------------------------------------------

@router.get("", response_model=LeadsListOut, dependencies=[Depends(require_internal_access)])
def list_leads(
    status_filter: Optional[str] = Query(None, alias="status"),
    latest_intent: Optional[str] = Query(None),
    latest_action: Optional[str] = Query(None),
    q: Optional[str] = Query(None, description="Search by phone or summary_hint"),
    date_from: Optional[str] = Query(None, description="Inclusive lower bound on created_at (YYYY-MM-DD or ISO 8601)"),
    date_to: Optional[str] = Query(None, description="Inclusive upper bound on created_at (YYYY-MM-DD or ISO 8601)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> LeadsListOut:
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available (demo mode)")

    # Normalize: FastAPI Query() objects are left unevaluated when the route function is
    # called directly (e.g., in tests).  Cast everything to its expected primitive type.
    def _s(v) -> Optional[str]:
        return v if isinstance(v, str) else None

    def _i(v, default: int) -> int:
        return v if isinstance(v, int) else default

    status_filter = _s(status_filter)
    latest_intent = _s(latest_intent)
    latest_action = _s(latest_action)
    q = _s(q)
    date_from = _s(date_from)
    date_to = _s(date_to)
    page = _i(page, 1)
    page_size = _i(page_size, 20)

    # Parse dates upfront so validation errors surface before any DB queries
    dt_from = _parse_date_param(date_from, "date_from") if date_from else None
    dt_to = _parse_date_param(date_to, "date_to", end_of_day=True) if date_to else None

    def _apply_common_filters(query):
        """Filters shared by both the status-count query and the main query."""
        if latest_intent:
            query = query.filter(Lead.latest_intent == latest_intent)
        if latest_action:
            query = query.filter(Lead.latest_action == latest_action)
        if q:
            term = f"%{q}%"
            query = query.filter(
                or_(Lead.phone.ilike(term), Lead.summary_hint.ilike(term))
            )
        if dt_from is not None:
            query = query.filter(Lead.created_at >= dt_from)
        if dt_to is not None:
            query = query.filter(Lead.created_at <= dt_to)
        return query

    # Status counts omit the status filter so all tabs remain meaningful
    counts_rows = _apply_common_filters(
        db.query(Lead.status, func.count(Lead.id)).group_by(Lead.status)
    ).all()
    status_counts: Dict[str, int] = {
        (s.value if hasattr(s, "value") else str(s)): c
        for s, c in counts_rows
    }

    # Main query (with optional status filter on top of common filters)
    main_q = _apply_common_filters(db.query(Lead))
    if status_filter:
        try:
            main_q = main_q.filter(Lead.status == LeadStatus(status_filter))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status_filter!r}")

    total = main_q.count()
    items = (
        main_q.order_by(Lead.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return LeadsListOut(
        items=items, total=total, page=page, page_size=page_size,
        status_counts=status_counts,
    )


@router.get("/stream")
async def leads_stream(
    request: Request,
    _auth: Optional[User] = Depends(require_internal_access_sse),
) -> StreamingResponse:
    """
    Server-Sent Events stream for realtime lead lifecycle events.

    Authentication (EventSource cannot send custom headers):
      • Authorization: Bearer <token>  — JWT with internal role (preferred)
      • ?token=<JWT>                   — JWT via query param for EventSource
      • X-Internal-Api-Key header      — API key (legacy)
      • ?api_key=<key>                 — API key via query param for EventSource

    Events emitted:
      lead.created, lead.updated, lead.delivery_failed, lead.closed
    Control events (client should ignore):
      connected, ping
    """

    from app.services.lead_events import lead_event_bus

    queue = lead_event_bus.subscribe()

    async def event_generator():
        try:
            # Send immediate confirmation so client knows the stream is live
            yield (
                f"data: {json.dumps({'event_type': 'connected', 'subscriber_count': lead_event_bus.subscriber_count}, ensure_ascii=False)}\n\n"
            )
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=20.0)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    # Check disconnect before sending heartbeat
                    if await request.is_disconnected():
                        break
                    yield f"data: {json.dumps({'event_type': 'ping'}, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.warning("leads_stream | generator_error | %s", exc)
        finally:
            lead_event_bus.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # disable nginx response buffering
            "Connection": "keep-alive",
        },
    )


# ---------------------------------------------------------------------------
# Routes — per-lead operations (must be declared after /stream)
# ---------------------------------------------------------------------------

@router.get("/{lead_id}", response_model=LeadOut, dependencies=[Depends(require_internal_access)])
def get_lead(lead_id: uuid.UUID, db: Session = Depends(get_db)) -> LeadOut:
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available (demo mode)")
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


@router.post("/{lead_id}/close", response_model=LeadOut, dependencies=[Depends(require_internal_access)])
def close_lead(lead_id: uuid.UUID, db: Session = Depends(get_db)) -> LeadOut:
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available (demo mode)")
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    lead.status = LeadStatus.CLOSED
    db.commit()
    db.refresh(lead)
    logger.info("internal_leads | closed | lead_id=%s", lead_id)

    # Emit realtime event (non-blocking, never raises)
    try:
        from app.services.lead_events import lead_event_bus, build_lead_event
        lead_event_bus.broadcast_sync(build_lead_event("lead.closed", lead))
    except Exception as exc:
        logger.debug("lead_events | emit skipped: %s", exc)

    return lead


@router.post("/{lead_id}/crm/retry", response_model=LeadOut, dependencies=[Depends(require_internal_access)])
def retry_lead_crm_sync(lead_id: uuid.UUID, db: Session = Depends(get_db)) -> LeadOut:
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available (demo mode)")
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    from app.services.crm_sync_service import retry_crm_sync
    result = retry_crm_sync(lead_id, db)
    if not result.get("ok"):
        reason = result.get("reason")
        if reason == "lead_not_failed":
            raise HTTPException(status_code=409, detail="CRM retry allowed only when crm_status=failed")
        if reason == "max_retries_reached":
            raise HTTPException(status_code=409, detail="CRM retry limit reached")
        raise HTTPException(status_code=500, detail="CRM retry failed")

    db.refresh(lead)
    return lead
