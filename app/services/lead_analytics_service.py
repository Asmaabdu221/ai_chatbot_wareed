"""
Lead Analytics Service — V1

Computes summary, distribution, trend, and efficiency metrics from the Lead table.
All aggregations are done in Python (not SQL) for cross-database compatibility
(PostgreSQL in production, SQLite in tests).

Limitation note:
  The Lead model stores created_at and delivered_at but NOT closed_at.
  "Average close time" is therefore computed as average time from lead capture
  (created_at) to delivery (delivered_at) for DELIVERED leads only.
  Closed leads that were never delivered cannot contribute to this metric.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.db.models import Lead

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _status_str(status_val) -> str:
    """Return the string value of a status field (handles enum or plain str)."""
    return status_val.value if hasattr(status_val, "value") else str(status_val)


def _to_naive_utc(dt: datetime) -> datetime:
    """Normalise a datetime to naive UTC for arithmetic."""
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _date_key(dt: datetime) -> str:
    """Return the YYYY-MM-DD date key for a datetime, normalised to UTC."""
    return _to_naive_utc(dt).date().isoformat()


def _apply_date_filters(query, dt_from: Optional[datetime], dt_to: Optional[datetime]):
    if dt_from is not None:
        query = query.filter(Lead.created_at >= dt_from)
    if dt_to is not None:
        query = query.filter(Lead.created_at <= dt_to)
    return query


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_lead_analytics(
    db: Session,
    dt_from: Optional[datetime] = None,
    dt_to: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Compute all analytics metrics for the given optional date range.

    Returns a single dict ready for JSON serialisation:
    {
      summary, rates, avg_delivery_time_hours,
      by_intent, by_action, by_status, trend
    }
    """
    q = db.query(Lead)
    q = _apply_date_filters(q, dt_from, dt_to)
    leads = q.order_by(Lead.created_at.asc()).all()

    total = len(leads)

    # --- Status breakdown ---
    status_counter: Counter = Counter()
    for lead in leads:
        status_counter[_status_str(lead.status)] += 1

    new_count = status_counter.get("new", 0)
    delivered_count = status_counter.get("delivered", 0)
    failed_count = status_counter.get("failed", 0)
    closed_count = status_counter.get("closed", 0)

    # --- CRM breakdown ---
    crm_counter: Counter = Counter((lead.crm_status or "pending") for lead in leads)
    crm_synced = crm_counter.get("synced", 0)
    crm_failed = crm_counter.get("failed", 0)
    crm_pending = crm_counter.get("pending", 0)
    crm_disabled = crm_counter.get("disabled", 0)
    crm_attempted = crm_synced + crm_failed

    # --- Rate metrics ---
    # delivery_failure_rate = failed / (delivered + failed) — only leads that were attempted
    delivery_attempted = delivered_count + failed_count
    delivery_failure_rate = (
        round(failed_count / delivery_attempted, 4) if delivery_attempted > 0 else 0.0
    )
    close_rate = round(closed_count / total, 4) if total > 0 else 0.0

    # --- Average delivery time (created_at → delivered_at for DELIVERED leads) ---
    delivery_seconds: list[float] = []
    for lead in leads:
        if (
            _status_str(lead.status) == "delivered"
            and lead.delivered_at is not None
            and lead.created_at is not None
        ):
            delta = (
                _to_naive_utc(lead.delivered_at) - _to_naive_utc(lead.created_at)
            ).total_seconds()
            if delta >= 0:
                delivery_seconds.append(delta)

    avg_delivery_time_hours: Optional[float] = None
    if delivery_seconds:
        avg_delivery_time_hours = round(
            sum(delivery_seconds) / len(delivery_seconds) / 3600, 3
        )

    # --- Distribution by intent ---
    intent_counter: Counter = Counter(
        lead.latest_intent or "(unknown)" for lead in leads
    )

    # --- Distribution by action ---
    action_counter: Counter = Counter(
        lead.latest_action or "(unknown)" for lead in leads
    )

    # --- Trend (leads by day, ascending) ---
    trend_counter: Counter = Counter()
    for lead in leads:
        if lead.created_at is not None:
            trend_counter[_date_key(lead.created_at)] += 1

    trend = sorted(
        [{"date": date, "count": cnt} for date, cnt in trend_counter.items()],
        key=lambda x: x["date"],
    )

    return {
        "summary": {
            "total_leads": total,
            "new_leads": new_count,
            "delivered_leads": delivered_count,
            "failed_leads": failed_count,
            "closed_leads": closed_count,
            "crm_synced_leads": crm_synced,
            "crm_failed_leads": crm_failed,
            "crm_pending_leads": crm_pending,
            "crm_disabled_leads": crm_disabled,
        },
        "rates": {
            "delivery_failure_rate": delivery_failure_rate,
            "close_rate": close_rate,
            "crm_failure_rate": round(crm_failed / total, 4) if total > 0 else 0.0,
            "crm_sync_success_rate": round(crm_synced / crm_attempted, 4) if crm_attempted > 0 else 0.0,
            "crm_sync_failure_rate": round(crm_failed / crm_attempted, 4) if crm_attempted > 0 else 0.0,
        },
        "avg_delivery_time_hours": avg_delivery_time_hours,
        "by_intent": [
            {"intent": k, "count": v}
            for k, v in intent_counter.most_common()
        ],
        "by_action": [
            {"action": k, "count": v}
            for k, v in action_counter.most_common()
        ],
        "by_status": [
            {"status": k, "count": v}
            for k, v in sorted(status_counter.items())
        ],
        "by_crm_status": [
            {"status": k, "count": v}
            for k, v in sorted(crm_counter.items())
        ],
        "retry_distribution": [
            {"retry_count": retry_count, "count": count}
            for retry_count, count in sorted(
                Counter(int(lead.crm_retry_count or 0) for lead in leads).items(),
                key=lambda item: item[0],
            )
        ],
        "trend": trend,
    }
