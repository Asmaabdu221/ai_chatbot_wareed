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
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import get_db
from app.db.models import Lead, LeadStatus

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/internal/leads", tags=["internal-leads"])


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _require_api_key(x_internal_api_key: str = Header(default="")) -> None:
    """Dependency for non-SSE routes (reads from header only)."""
    expected = (settings.INTERNAL_LEADS_API_KEY or "").strip()
    if not expected:
        return  # dev mode: no key configured → open
    if x_internal_api_key != expected:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid API key")


def _check_key(key: str) -> None:
    """Validate key value directly (used where the source varies)."""
    expected = (settings.INTERNAL_LEADS_API_KEY or "").strip()
    if not expected:
        return
    if key != expected:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid API key")


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

    class Config:
        from_attributes = True


class LeadsListOut(BaseModel):
    items: List[LeadOut]
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------------------
# Routes — list and SSE (declared before /{lead_id} to avoid shadowing)
# ---------------------------------------------------------------------------

@router.get("", response_model=LeadsListOut, dependencies=[Depends(_require_api_key)])
def list_leads(
    status_filter: Optional[str] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> LeadsListOut:
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available (demo mode)")

    q = db.query(Lead)
    if status_filter:
        try:
            q = q.filter(Lead.status == LeadStatus(status_filter))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status_filter!r}")

    total = q.count()
    items = (
        q.order_by(Lead.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return LeadsListOut(items=items, total=total, page=page, page_size=page_size)


@router.get("/stream")
async def leads_stream(
    request: Request,
    api_key: str = Query(default="", description="API key (EventSource cannot set custom headers)"),
    x_internal_api_key: str = Header(default=""),
) -> StreamingResponse:
    """
    Server-Sent Events stream for realtime lead lifecycle events.

    EventSource (browser native API) cannot send custom headers, so the API key
    may be passed as ?api_key=... query parameter as an alternative to the header.

    Events emitted:
      lead.created, lead.updated, lead.delivery_failed, lead.closed
    Control events (client should ignore):
      connected, ping
    """
    # Accept key from header (API calls) OR query param (EventSource)
    key = x_internal_api_key or api_key
    _check_key(key)

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

@router.get("/{lead_id}", response_model=LeadOut, dependencies=[Depends(_require_api_key)])
def get_lead(lead_id: uuid.UUID, db: Session = Depends(get_db)) -> LeadOut:
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available (demo mode)")
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


@router.post("/{lead_id}/close", response_model=LeadOut, dependencies=[Depends(_require_api_key)])
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
