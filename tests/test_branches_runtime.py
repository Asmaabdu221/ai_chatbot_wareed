"""P0/P1 branches runtime: resolver, intent detection, entity memory."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.services.runtime.runtime_router import _looks_like_branch_query, route_runtime_message
from app.services.runtime.branches_resolver import resolve_branches_query
from app.services.runtime.entity_memory import load_entity_memory, update_entity_memory


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
        "hours": "8:00 صباحاً - 10:00 مساءً",
        "working_hours": "8:00 صباحاً - 10:00 مساءً",
        "map_url": "https://maps.example.com/riyadh_olaya",
        "maps_url": "https://maps.example.com/riyadh_olaya",
        "location_url": "https://maps.example.com/riyadh_olaya",
        "latitude": 24.69,
        "longitude": 46.68,
        "contact_phone": "920003694",
        "is_active": True,
        "raw_text": "فرع العليا الرياض",
        "raw_norm": "فرع العليا الرياض",
        "section": "مواقع فروع الرياض",
        "section_norm": "مواقع فروع الرياض",
        "address": "طريق الملك فهد، العليا، الرياض",
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
        "hours": "7:00 صباحاً - 9:00 مساءً",
        "working_hours": "7:00 صباحاً - 9:00 مساءً",
        "map_url": "https://maps.example.com/riyadh_nuzha",
        "maps_url": "https://maps.example.com/riyadh_nuzha",
        "location_url": "https://maps.example.com/riyadh_nuzha",
        "latitude": 24.78,
        "longitude": 46.72,
        "contact_phone": "920003694",
        "is_active": True,
        "raw_text": "فرع النزهة الرياض",
        "raw_norm": "فرع النزهه الرياض",
        "section": "مواقع فروع الرياض",
        "section_norm": "مواقع فروع الرياض",
        "address": "حي النزهة، الرياض",
    },
    {
        "source": "branches",
        "id": "branch::jeddah_main",
        "city": "جدة",
        "city_norm": "جده",
        "district": "الحمدانية",
        "district_norm": "الحمدانيه",
        "branch_name": "فرع جدة الرئيسي",
        "branch_norm": "فرع جده الرييسي",
        "hours": "8:00 صباحاً - 8:00 مساءً",
        "working_hours": "8:00 صباحاً - 8:00 مساءً",
        "map_url": "https://maps.example.com/jeddah_main",
        "maps_url": "https://maps.example.com/jeddah_main",
        "location_url": "https://maps.example.com/jeddah_main",
        "latitude": 21.54,
        "longitude": 39.18,
        "contact_phone": "920003694",
        "is_active": True,
        "raw_text": "فرع جدة الرئيسي",
        "raw_norm": "فرع جده الرييسي",
        "section": "مواقع فروع جدة",
        "section_norm": "مواقع فروع جده",
        "address": "حي الحمدانية، جدة",
    },
]


@pytest.fixture()
def branches_data(monkeypatch):
    import app.services.runtime.branches_resolver as br_mod
    original_fn = br_mod.load_branches_records
    original_fn.cache_clear()
    monkeypatch.setattr(br_mod, "load_branches_records", lambda: list(_BRANCH_ROWS))
    yield _BRANCH_ROWS
    original_fn.cache_clear()


# ─── C: branch intent detection ───────────────────────────────────────────────

@pytest.mark.parametrize("query", [
    "فروعكم",
    "وين فروعكم",
    "موقعكم",
    "وين موقعكم",
    "اقرب فرع بالرياض",
    "عندكم فرع في جدة",
    "موقع الفرع",
    "وين اقرب فرع",
])
def test_looks_like_branch_query_positive(query):
    assert _looks_like_branch_query(query) is True, f"Expected branch-like: {query!r}"


@pytest.mark.parametrize("query", [
    "كم سعر تحليل HBA1C",
    "باقة الرمضانية",
    "تحليل السكر التراكمي",
    "متى تطلع نتيجتي",
    "هل يرسلون النتائج إلكترونياً",
])
def test_looks_like_branch_query_negative(query):
    assert _looks_like_branch_query(query) is False, f"Expected NOT branch-like: {query!r}"


# ─── C: branches resolver ─────────────────────────────────────────────────────

def test_generic_branches_query_matches(branches_data):
    result = resolve_branches_query("وين فروعكم")
    assert result["matched"] is True
    assert result["route"] == "branches_generic"


def test_mawqe3kom_query_matches(branches_data):
    """'موقعكم' must match after adding it to _GENERIC_BRANCHES_HINTS."""
    result = resolve_branches_query("موقعكم")
    assert result["matched"] is True


def test_city_query_riyadh_lists_branches(branches_data):
    result = resolve_branches_query("فروع الرياض")
    assert result["matched"] is True
    assert "الرياض" in result.get("answer", "")


def test_city_query_jeddah_lists_branch(branches_data):
    result = resolve_branches_query("ابي فرع في جده")
    assert result["matched"] is True
    answer = result.get("answer", "")
    assert "جدة" in answer or "جده" in answer


def test_specific_branch_name_match(branches_data):
    result = resolve_branches_query("فرع العليا")
    assert result["matched"] is True
    assert "العليا" in result.get("answer", "")


def test_unknown_city_returns_matched_with_city_not_found(branches_data):
    result = resolve_branches_query("عندكم فرع في عبها")
    assert result["matched"] is True
    assert result["meta"]["query_type"] in ("city_not_found", "generic_overview")


def test_empty_query_returns_no_match(branches_data):
    result = resolve_branches_query("")
    assert result["matched"] is False


# ─── B: entity memory after branch hit ────────────────────────────────────────

def test_update_entity_memory_branch_sets_intent():
    cid = uuid4()
    update_entity_memory(
        cid,
        last_intent="branch",
        last_branch={"id": "branch::riyadh_olaya", "label": "فرع العليا", "city": "الرياض"},
    )
    mem = load_entity_memory(cid)
    assert mem["last_intent"] == "branch"
    assert mem["last_branch"]["label"] == "فرع العليا"
    assert mem["last_branch"]["city"] == "الرياض"
    assert mem["last_intent_has_entity"] is True


def test_update_entity_memory_branch_has_entity_flag():
    cid = uuid4()
    update_entity_memory(
        cid,
        last_intent="branch",
        last_branch={"id": "b1", "label": "فرع النزهة", "city": "الرياض"},
    )
    mem = load_entity_memory(cid)
    assert mem["last_intent_has_entity"] is True


def test_entity_memory_missing_label_does_not_set_flag():
    cid = uuid4()
    update_entity_memory(
        cid,
        last_intent="branch",
        last_branch={"id": "", "label": "", "city": ""},
    )
    mem = load_entity_memory(cid)
    assert mem["last_intent_has_entity"] is False


# ─── A: end-to-end runtime router with faq_only_runtime_mode=True ─────────────

def test_runtime_router_branch_query_routes_to_branches(branches_data):
    result = route_runtime_message(
        "وين فروعكم",
        conversation_id=uuid4(),
        faq_only_runtime_mode=True,
    )
    assert result["matched"] is True
    assert result["source"] == "branches"


def test_runtime_router_mawqe3kom_routes_to_branches(branches_data):
    """'موقعكم' should route to branches after the intent-detection fix."""
    result = route_runtime_message(
        "موقعكم",
        conversation_id=uuid4(),
        faq_only_runtime_mode=True,
    )
    assert result["matched"] is True
    assert result["source"] == "branches"


def test_runtime_router_greeting_returns_matched():
    result = route_runtime_message("مرحبا", faq_only_runtime_mode=True)
    assert result["matched"] is True
    assert result["route"] == "greeting"
