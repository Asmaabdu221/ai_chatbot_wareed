"""Lightweight per-conversation entity memory helpers."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from app.services.context_cache import get_context_cache


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _memory_key(conversation_id: UUID) -> str:
    return f"entity_memory:{conversation_id}"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _default_memory() -> dict[str, Any]:
    return {
        "last_intent": "",
        "last_test": {"id": "", "label": ""},
        "last_package": {"id": "", "label": ""},
        "last_branch": {"id": "", "label": "", "city": ""},
        "updated_at": "",
        "expires_at": "",
    }


def load_entity_memory(conversation_id: UUID | None) -> dict[str, Any]:
    if conversation_id is None:
        return _default_memory()
    raw = get_context_cache().get(_memory_key(conversation_id))
    if not raw:
        return _default_memory()
    try:
        parsed = json.loads(raw)
    except Exception:
        return _default_memory()
    if not isinstance(parsed, dict):
        return _default_memory()
    out = _default_memory()
    out.update(parsed)
    return out


def save_entity_memory(conversation_id: UUID | None, payload: dict[str, Any]) -> dict[str, Any]:
    if conversation_id is None:
        return _default_memory()
    now = _utc_now()
    out = _default_memory()
    out.update(payload or {})
    out["updated_at"] = now.isoformat()
    out["expires_at"] = (now + timedelta(minutes=15)).isoformat()
    get_context_cache().set(_memory_key(conversation_id), json.dumps(out, ensure_ascii=False))
    return out


def update_entity_memory(
    conversation_id: UUID | None,
    *,
    last_intent: str = "",
    last_test: dict[str, str] | None = None,
    last_package: dict[str, str] | None = None,
    last_branch: dict[str, str] | None = None,
) -> dict[str, Any]:
    current = load_entity_memory(conversation_id)
    if _safe_str(last_intent):
        current["last_intent"] = _safe_str(last_intent)
    if isinstance(last_test, dict):
        current["last_test"] = {
            "id": _safe_str(last_test.get("id")),
            "label": _safe_str(last_test.get("label")),
        }
    if isinstance(last_package, dict):
        current["last_package"] = {
            "id": _safe_str(last_package.get("id")),
            "label": _safe_str(last_package.get("label")),
        }
    if isinstance(last_branch, dict):
        current["last_branch"] = {
            "id": _safe_str(last_branch.get("id")),
            "label": _safe_str(last_branch.get("label")),
            "city": _safe_str(last_branch.get("city")),
        }
    return save_entity_memory(conversation_id, current)
