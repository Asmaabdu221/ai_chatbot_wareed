"""
Internal Leads API — staff/dashboard integration endpoint.

All routes require an `X-Internal-Api-Key` header matching
settings.INTERNAL_LEADS_API_KEY.  When the key is empty (dev mode)
the header check is skipped so local testing works without configuration.

Routes
------
  GET  /internal/leads            List leads (paginated, filterable by status)
  GET  /internal/leads/{lead_id}  Retrieve a single lead
  POST /internal/leads/{lead_id}/close   Mark a lead as closed
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import get_db
from app.db.models import Lead, LeadStatus

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/internal/leads", tags=["internal-leads"])


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

def _require_api_key(x_internal_api_key: str = Header(default="")) -> None:
    expected = (settings.INTERNAL_LEADS_API_KEY or "").strip()
    if not expected:
        return  # dev mode: no key configured → open
    if x_internal_api_key != expected:
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
# Routes
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
    return lead
