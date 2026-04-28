"""
Per-conversation dialogue state — Phase 1 Dialogue Manager.

Schema:
{
    "conversation_id": str,
    "active_domain": "test" | "branch" | "package" | "none",
    "active_entity_name": str | null,
    "updated_at": ISO-8601 str,
    "expires_at": ISO-8601 str
}

Storage  : ContextCache (same backend as entity_memory / selection_state).
TTL      : 30 minutes (soft expiry stored in the JSON payload).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from app.services.context_cache import get_context_cache

logger = logging.getLogger(__name__)

_TTL_MINUTES = 30
_KEY_PREFIX = "dialogue_state:"


def _key(conversation_id: str | UUID) -> str:
    return f"{_KEY_PREFIX}{conversation_id}"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _default(conversation_id: str) -> dict[str, Any]:
    return {
        "conversation_id": conversation_id,
        "active_domain": "none",
        "active_entity_name": None,
        "active_package_name": None,
        "active_package_id": None,
        "active_package_price": None,
        "active_branch_name": None,
        "active_symptoms": [],
        "active_result_test_name": None,
        "active_result_value": None,
        "updated_at": "",
        "expires_at": "",
    }


def get_dialogue_state(conversation_id: str | UUID) -> dict[str, Any]:
    """Return dialogue state for this conversation, or a fresh default."""
    cid = str(conversation_id)
    try:
        raw = get_context_cache().get(_key(cid))
    except Exception:
        return _default(cid)
    if not raw:
        return _default(cid)
    try:
        parsed = json.loads(raw)
    except Exception:
        return _default(cid)
    if not isinstance(parsed, dict):
        return _default(cid)
    # Soft expiry check
    expires_at = str(parsed.get("expires_at") or "")
    if expires_at:
        try:
            dt = datetime.fromisoformat(expires_at)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt <= _utc_now():
                return _default(cid)
        except Exception:
            pass
    out = _default(cid)
    out.update(parsed)
    return out


def set_dialogue_state(conversation_id: str | UUID, state: dict[str, Any]) -> dict[str, Any]:
    """Persist dialogue state, stamping updated_at and expires_at."""
    cid = str(conversation_id)
    now = _utc_now()
    out = dict(state)
    out["conversation_id"] = cid
    out["updated_at"] = now.isoformat()
    out["expires_at"] = (now + timedelta(minutes=_TTL_MINUTES)).isoformat()
    try:
        get_context_cache().set(_key(cid), json.dumps(out, ensure_ascii=False))
    except Exception as exc:
        logger.warning("dialogue_state | set failed | cid=%.8s | reason=%s", cid, exc)
    return out
