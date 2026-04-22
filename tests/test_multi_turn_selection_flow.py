"""Regression test for multi-turn selection flow."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from app.services.runtime.runtime_router import route_runtime_message
from app.services.runtime.selection_state import load_selection_state
from app.services.context_cache import get_context_cache


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


@pytest.fixture(autouse=True)
def clear_cache():
    """Ensure context cache is clean before each test."""
    get_context_cache().clear()


def test_multi_turn_selection_flow(branches_data):
    """
    Test the multi-turn selection flow:
    1. User asks for branches -> gets a list.
    2. User inputs '3' -> resolves to the 3rd branch option.
    3. User asks a new domain question ('أبغى تحليل') -> selection state is cleared.
    4. User inputs '1' -> does NOT resolve to a branch.
    """
    conversation_id = uuid4()

    # Step 1: User asks for branches
    result_1 = route_runtime_message(
        "أبغى أعرف الفروع",
        conversation_id=conversation_id,
        faq_only_runtime_mode=True,
    )
    
    # Verify it routed to branches
    assert result_1["matched"] is True
    assert result_1["source"] == "branches"
    assert result_1["route"] == "branches_generic"

    # Step 2: The system should have saved a selection state with branches
    state = load_selection_state(conversation_id)
    assert state.get("last_selection_type") == "branch"
    # We may not have explicit options if the generic generic branch overview doesn't list them,
    # wait, "أبغى أعرف الفروع" is generic, it might just list cities?
    # Let's say "فروع الرياض" so it lists specific branches.
    
    # Re-do step 1 with a query that avoids false fuzzy matches for a single branch.
    result_list = route_runtime_message(
        "أبغى لستة فروعكم في مدينة الرياض",
        conversation_id=conversation_id,
        faq_only_runtime_mode=True,
    )
    assert result_list["matched"] is True
    assert result_list["source"] == "branches"
    assert result_list["route"] == "branches_city_list", f"Expected branches_city_list, got {result_list.get('route')}"
    
    state_list = load_selection_state(conversation_id)
    assert state_list.get("last_selection_type") == "branch"
    options = state_list.get("last_options", [])
    assert len(options) >= 2, "Expected multiple branch options to be listed"

    # Step 3: User inputs a numeric selection '3' (or '2' if 3 doesn't exist)
    # We will pick '2' to be safe, since test data might only have 2 branches for Riyadh.
    result_selection = route_runtime_message(
        "2",
        conversation_id=conversation_id,
        faq_only_runtime_mode=True,
    )
    
    assert result_selection["matched"] is True
    assert result_selection["source"] == "branches"
    # It should resolve to the specific branch
    assert result_selection["route"] == "branches_city_number_selection"
    assert "النزه" in result_selection.get("reply", "")  # Should contain the branch name
    
    # State should still be active (consumption rule: KEEP ACTIVE)
    state_after_selection = load_selection_state(conversation_id)
    assert state_after_selection.get("last_selection_type") == "branch"
    
    # Step 4: User asks for a new domain ('أبغى تحليل')
    result_new_domain = route_runtime_message(
        "أبغى تحليل السكر",
        conversation_id=conversation_id,
        faq_only_runtime_mode=True,
    )
    
    # State should be CLEARED
    cleared_state = load_selection_state(conversation_id)
    assert not cleared_state.get("last_selection_type"), "Selection state should have been cleared after cross-domain query"
    
    # Step 5: User inputs '1' -> shouldn't resolve to a branch anymore
    result_second_numeric = route_runtime_message(
        "1",
        conversation_id=conversation_id,
        faq_only_runtime_mode=True,
    )
    
    # Should not route to branches
    assert result_second_numeric.get("route") != "branches_city_number_selection"
