"""Recent runtime conversation context helpers.

Behavior must remain identical to original helper logic.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.models import Conversation


def to_utc_naive(dt: datetime | None) -> datetime | None:
    """Convert datetime to naive UTC for safe comparisons."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def extract_recent_runtime_messages(
    db: Session,
    conversation: Conversation,
    get_history_for_ai: Callable[..., list[dict[str, Any]]],
    ttl_minutes: int = 15,
) -> tuple[list[dict[str, str]], bool]:
    """Return recent conversation role/content messages within TTL."""
    now_utc = datetime.utcnow()
    cutoff = now_utc - timedelta(minutes=ttl_minutes)
    history = get_history_for_ai(
        db,
        conversation,
        max_messages=20,
        include_created_at=True,
    )

    recent: list[dict[str, str]] = []
    for item in history:
        created_at = to_utc_naive(item.get("created_at"))
        if created_at is None:
            continue
        if created_at >= cutoff:
            role = str(item.get("role") or "").strip().lower()
            content = str(item.get("content") or "").strip()
            if not role or not content:
                continue
            recent.append({"role": role, "content": content})

    context_used = bool(recent)
    return recent, context_used
