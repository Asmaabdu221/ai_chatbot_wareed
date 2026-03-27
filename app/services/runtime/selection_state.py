"""Per-conversation selection state for numbered options."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from app.services.context_cache import get_context_cache


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _state_key(conversation_id: UUID) -> str:
    return f"selection_state:{conversation_id}"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _default_state() -> dict[str, Any]:
    return {
        "last_options": [],
        "last_selection_type": "",
        "last_city": "",
        "last_selected_id": "",
        "last_selected_label": "",
        "query_type": "",
        "updated_at": "",
        "expires_at": "",
    }


def _is_expired(state: dict[str, Any]) -> bool:
    expires_at = _safe_str(state.get("expires_at"))
    if not expires_at:
        return True
    try:
        dt = datetime.fromisoformat(expires_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt <= _utc_now()
    except Exception:
        return True


def load_selection_state(conversation_id: UUID | None) -> dict[str, Any]:
    if conversation_id is None:
        return _default_state()
    raw = get_context_cache().get(_state_key(conversation_id))
    if not raw:
        return _default_state()
    try:
        parsed = json.loads(raw)
    except Exception:
        return _default_state()
    if not isinstance(parsed, dict):
        return _default_state()
    state = _default_state()
    state.update(parsed)
    if _is_expired(state):
        clear_selection_state(conversation_id)
        return _default_state()
    return state


def save_selection_state(
    conversation_id: UUID | None,
    *,
    options: list[dict[str, Any]],
    selection_type: str,
    city: str = "",
    query_type: str = "",
) -> dict[str, Any]:
    if conversation_id is None:
        return _default_state()
    now = _utc_now()
    state = _default_state()
    state["last_options"] = list(options or [])
    state["last_selection_type"] = _safe_str(selection_type)
    state["last_city"] = _safe_str(city)
    state["query_type"] = _safe_str(query_type)
    state["updated_at"] = now.isoformat()
    state["expires_at"] = (now + timedelta(minutes=15)).isoformat()
    get_context_cache().set(_state_key(conversation_id), json.dumps(state, ensure_ascii=False))
    return state


def clear_selection_state(conversation_id: UUID | None) -> None:
    if conversation_id is None:
        return
    state = _default_state()
    now = _utc_now()
    state["updated_at"] = now.isoformat()
    state["expires_at"] = now.isoformat()
    get_context_cache().set(_state_key(conversation_id), json.dumps(state, ensure_ascii=False))
