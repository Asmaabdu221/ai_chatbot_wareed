"""
Internal Analytics API — staff/supervisor reporting endpoint.

Routes
------
  GET /internal/analytics/leads   Aggregated lead metrics (summary, rates, trend, distributions)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.permissions import require_internal_access
from app.db import get_db
from app.db.models import User
from app.services.lead_analytics_service import get_lead_analytics

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/internal/analytics", tags=["internal-analytics"])


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class SummaryOut(BaseModel):
    total_leads: int
    new_leads: int
    delivered_leads: int
    failed_leads: int
    closed_leads: int
    crm_synced_leads: int = 0
    crm_failed_leads: int = 0
    crm_pending_leads: int = 0
    crm_disabled_leads: int = 0


class RatesOut(BaseModel):
    delivery_failure_rate: float
    close_rate: float
    crm_failure_rate: float = 0.0
    crm_sync_success_rate: float = 0.0
    crm_sync_failure_rate: float = 0.0


class IntentCountOut(BaseModel):
    intent: str
    count: int


class ActionCountOut(BaseModel):
    action: str
    count: int


class StatusCountOut(BaseModel):
    status: str
    count: int


class CrmStatusCountOut(BaseModel):
    status: str
    count: int


class TrendPointOut(BaseModel):
    date: str
    count: int


class RetryDistributionOut(BaseModel):
    retry_count: int
    count: int


class LeadAnalyticsOut(BaseModel):
    summary: SummaryOut
    rates: RatesOut
    avg_delivery_time_hours: Optional[float]
    by_intent: List[IntentCountOut]
    by_action: List[ActionCountOut]
    by_status: List[StatusCountOut]
    by_crm_status: List[CrmStatusCountOut] = []
    retry_distribution: List[RetryDistributionOut] = []
    trend: List[TrendPointOut]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_date(value: Optional[str], param_name: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid date format for '{param_name}'. Use YYYY-MM-DD or ISO 8601.",
        )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/leads", response_model=LeadAnalyticsOut)
def get_analytics(
    date_from: Optional[str] = Query(None, description="Start date (YYYY-MM-DD or ISO 8601)"),
    date_to: Optional[str] = Query(None, description="End date (YYYY-MM-DD or ISO 8601)"),
    db: Session = Depends(get_db),
    _user: Optional[User] = Depends(require_internal_access),
) -> LeadAnalyticsOut:
    dt_from = _parse_date(date_from if isinstance(date_from, str) else None, "date_from")
    dt_to = _parse_date(date_to if isinstance(date_to, str) else None, "date_to")

    data = get_lead_analytics(db, dt_from=dt_from, dt_to=dt_to)
    return LeadAnalyticsOut(**data)
