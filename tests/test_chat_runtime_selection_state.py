from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

from app.api import chat as chat_api
from app.api.chat import ChatRequest
from app.services.context_cache import get_context_cache
from app.services.runtime.selection_state import load_selection_state, save_selection_state


class _AllowAllRateLimiter:
    def is_allowed(self, _client_id: str):
        return True, 0


class _NoopUsageTracker:
    def record(self, *_args, **_kwargs):
        return None


class _NoopSmartCache:
    def get(self, *_args, **_kwargs):
        return None

    def set(self, *_args, **_kwargs):
        return None


class _DummyHttpRequest:
    client = SimpleNamespace(host="127.0.0.1")


_BRANCH_ROWS = [
    {
        "source": "branches",
        "id": "branch::riyadh_olaya",
        "city": "الرياض",
        "city_norm": "الرياض",
        "district": "العليا",
        "district_norm": "العليا",
        "branch_name": "فرع العليا",
        "branch_norm": "فرع العليا",
        "is_active": True,
        "raw_norm": "فرع العليا الرياض",
        "address": "العليا - الرياض",
        "working_hours": "8:00 صباحاً - 10:00 مساءً",
        "map_url": "https://maps.example.com/riyadh_olaya",
    },
    {
        "source": "branches",
        "id": "branch::riyadh_nuzha",
        "city": "الرياض",
        "city_norm": "الرياض",
        "district": "النزهة",
        "district_norm": "النزهه",
        "branch_name": "فرع النزهة",
        "branch_norm": "فرع النزهه",
        "is_active": True,
        "raw_norm": "فرع النزهه الرياض",
        "address": "النزهة - الرياض",
        "working_hours": "8:00 صباحاً - 10:00 مساءً",
        "map_url": "https://maps.example.com/riyadh_nuzha",
    },
]


def _call_chat(db, payload: ChatRequest):
    return asyncio.run(
        chat_api.chat_endpoint(
            http_request=_DummyHttpRequest(),
            request=payload,
            db=db,
            current_user=None,
        )
    )


def _patch_common(monkeypatch):
    monkeypatch.setattr(chat_api, "get_rate_limiter", lambda: _AllowAllRateLimiter())
    monkeypatch.setattr(chat_api, "get_usage_tracker", lambda: _NoopUsageTracker())
    monkeypatch.setattr(chat_api, "get_smart_cache", lambda: _NoopSmartCache())
    monkeypatch.setattr(chat_api, "route_question", lambda _msg: ("", None))


def test_chat_endpoint_keeps_branch_state_for_numeric_followup(db, monkeypatch):
    _patch_common(monkeypatch)
    get_context_cache().clear()

    import app.services.runtime.branches_resolver as br_mod

    original_fn = br_mod.load_branches_records
    original_fn.cache_clear()
    monkeypatch.setattr(br_mod, "load_branches_records", lambda: list(_BRANCH_ROWS))

    first = _call_chat(
        db,
        ChatRequest(message="أبغى لستة فروعكم في مدينة الرياض", include_knowledge=True),
    )
    assert first.model == "runtime"
    assert "اختر رقم أو اسم الفرع" in first.reply

    state_after_list = load_selection_state(first.conversation_id)
    assert state_after_list.get("last_selection_type") == "branch"
    assert len(state_after_list.get("last_options") or []) >= 2

    second = _call_chat(
        db,
        ChatRequest(
            message="2",
            include_knowledge=True,
            user_id=first.user_id,
            conversation_id=first.conversation_id,
        ),
    )
    assert second.model == "runtime"
    assert "فرع النزه" in second.reply
    assert "لا أملك معلومات" not in second.reply

    state_after_numeric = load_selection_state(first.conversation_id)
    assert state_after_numeric.get("last_selection_type") == "branch"


def test_chat_endpoint_clears_selection_state_on_real_domain_switch(db, monkeypatch):
    _patch_common(monkeypatch)
    get_context_cache().clear()

    setup = _call_chat(
        db,
        ChatRequest(message="تهيئة", include_knowledge=True),
    )
    save_selection_state(
        setup.conversation_id,
        options=[{"id": "branch::1", "label": "فرع العليا"}],
        selection_type="branch",
        city="الرياض",
    )

    def _fake_tests_route(_text, **_kwargs):
        return {
            "matched": True,
            "reply": "سعر التحليل 100 ريال",
            "source": "tests",
            "route": "tests_business_price",
            "meta": {"query_type": "test_price_query"},
        }

    monkeypatch.setattr(
        "app.services.runtime.runtime_router.route_runtime_message",
        _fake_tests_route,
    )

    _call_chat(
        db,
        ChatRequest(
            message="كم سعر تحليل السكر",
            include_knowledge=True,
            user_id=setup.user_id,
            conversation_id=setup.conversation_id,
        ),
    )
    state_after = load_selection_state(setup.conversation_id)
    assert state_after.get("last_selection_type") == ""
    assert state_after.get("last_options") == []


def test_chat_endpoint_treats_branch_source_alias_as_same_domain(db, monkeypatch):
    _patch_common(monkeypatch)
    get_context_cache().clear()

    setup = _call_chat(
        db,
        ChatRequest(message="تهيئة", include_knowledge=True),
    )
    save_selection_state(
        setup.conversation_id,
        options=[{"id": "branch::1", "label": "فرع العليا"}],
        selection_type="branch",
        city="الرياض",
    )

    def _fake_branch_alias_route(_text, **_kwargs):
        return {
            "matched": True,
            "reply": "فرع العليا",
            "source": "branch",
            "route": "branches_city_number_selection",
            "meta": {"query_type": "numeric_selection"},
        }

    monkeypatch.setattr(
        "app.services.runtime.runtime_router.route_runtime_message",
        _fake_branch_alias_route,
    )

    _call_chat(
        db,
        ChatRequest(
            message="1",
            include_knowledge=True,
            user_id=setup.user_id,
            conversation_id=setup.conversation_id,
        ),
    )
    state_after = load_selection_state(setup.conversation_id)
    assert state_after.get("last_selection_type") == "branch"
