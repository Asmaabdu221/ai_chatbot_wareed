from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.api import chat as chat_api
from app.api.chat import ChatRequest
from app.db.models import Conversation, Lead, User
from app.services.conversation_state import StateEnum, get_state_store


class _AllowAllRateLimiter:
    def is_allowed(self, _client_id: str):
        return True, 0


class _NoopUsageTracker:
    def record(self, *_args, **_kwargs):
        return None


class _NoopCache:
    def set(self, *_args, **_kwargs):
        return None


class _DummyHttpRequest:
    client = SimpleNamespace(host="127.0.0.1")


def _call_chat(db, payload: ChatRequest):
    return asyncio.run(
        chat_api.chat_endpoint(
            http_request=_DummyHttpRequest(),
            request=payload,
            db=db,
            current_user=None,
        )
    )


def _patch_safe_fast_path(monkeypatch):
    monkeypatch.setattr(chat_api, "get_rate_limiter", lambda: _AllowAllRateLimiter())
    monkeypatch.setattr(chat_api, "get_usage_tracker", lambda: _NoopUsageTracker())
    monkeypatch.setattr(chat_api, "get_smart_cache", lambda: _NoopCache())
    monkeypatch.setattr(chat_api, "route_question", lambda _msg: ("fixed", "ok"))
    from app.core.config import settings
    monkeypatch.setattr(settings, "CRM_SYNC_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "INTERNAL_LEADS_WEBHOOK_URL", "", raising=False)


def _clear_state_store():
    store = get_state_store()
    with store._lock:
        store._store.clear()


def test_chat_request_1_creates_user_and_conversation(db, monkeypatch):
    _clear_state_store()
    _patch_safe_fast_path(monkeypatch)
    users_before = db.query(User).count()
    conversations_before = db.query(Conversation).count()

    response = _call_chat(
        db,
        ChatRequest(message="hello", include_knowledge=True),
    )

    assert response.user_id is not None
    assert response.conversation_id is not None
    assert db.query(User).count() == users_before + 1
    assert db.query(Conversation).count() == conversations_before + 1


def test_chat_request_2_reuses_same_user_and_conversation(db, monkeypatch):
    _clear_state_store()
    _patch_safe_fast_path(monkeypatch)
    users_before = db.query(User).count()
    conversations_before = db.query(Conversation).count()

    first = _call_chat(
        db,
        ChatRequest(message="first", include_knowledge=True),
    )
    second = _call_chat(
        db,
        ChatRequest(
            message="second",
            include_knowledge=True,
            user_id=first.user_id,
            conversation_id=first.conversation_id,
        ),
    )

    assert second.user_id == first.user_id
    assert second.conversation_id == first.conversation_id
    assert db.query(User).count() == users_before + 1
    assert db.query(Conversation).count() == conversations_before + 1


def test_phone_capture_with_continuous_session_creates_lead(db, monkeypatch):
    _clear_state_store()
    _patch_safe_fast_path(monkeypatch)
    leads_before = db.query(Lead).count()

    first = _call_chat(
        db,
        ChatRequest(message="start", include_knowledge=True),
    )
    conversation_id = str(first.conversation_id)
    get_state_store().update(
        conversation_id,
        state=StateEnum.AWAITING_PHONE,
        pending_action="ask_phone",
        pending_intent_summary="customer service",
    )

    import app.services.lead_service as lead_service

    real_create = lead_service.create_lead_from_draft
    create_calls = {"count": 0}

    def _create_spy(draft, session):
        create_calls["count"] += 1
        return real_create(draft, session)

    monkeypatch.setattr(lead_service, "create_lead_from_draft", _create_spy)

    second = _call_chat(
        db,
        ChatRequest(
            message="0501234567",
            include_knowledge=True,
            user_id=first.user_id,
            conversation_id=first.conversation_id,
        ),
    )

    assert second.conversation_id == first.conversation_id
    assert create_calls["count"] == 1

    lead_rows = db.query(Lead).order_by(Lead.created_at.desc()).all()
    assert db.query(Lead).count() == leads_before + 1
    assert str(lead_rows[0].conversation_id) == conversation_id
    assert lead_rows[0].phone == "0501234567"


def test_external_widget_continuity_end_to_end(db, monkeypatch):
    _clear_state_store()
    _patch_safe_fast_path(monkeypatch)
    users_before = db.query(User).count()
    conversations_before = db.query(Conversation).count()
    leads_before = db.query(Lead).count()

    first = _call_chat(
        db,
        ChatRequest(message="I want to contact customer service", include_knowledge=True),
    )
    conversation_id = str(first.conversation_id)
    get_state_store().update(
        conversation_id,
        state=StateEnum.AWAITING_PHONE,
        pending_action="ask_phone",
        pending_intent_summary="I want to contact customer service",
    )

    second = _call_chat(
        db,
        ChatRequest(
            message="0501234567",
            include_knowledge=True,
            user_id=first.user_id,
            conversation_id=first.conversation_id,
        ),
    )

    assert second.user_id == first.user_id
    assert second.conversation_id == first.conversation_id
    assert db.query(User).count() == users_before + 1
    assert db.query(Conversation).count() == conversations_before + 1
    assert db.query(Lead).count() == leads_before + 1
