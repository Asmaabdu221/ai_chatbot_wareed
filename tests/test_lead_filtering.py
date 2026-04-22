"""
Backend tests for the advanced filtering on GET /api/internal/leads.

Coverage:
  1.  No filters — returns all leads (>= created count)
  2.  Filter by status
  3.  Filter by invalid status — 400
  4.  Filter by latest_intent
  5.  Filter by latest_action
  6.  Search by phone (q)
  7.  Search by summary_hint (q)
  8.  Date range: date_from only
  9.  Date range: date_to only
  10. Date range: combined date_from + date_to
  11. Combined filters (status + q)
  12. Invalid date_from — 400
  13. Invalid date_to — 400
  14. Pagination with filters
  15. status_counts always reflects all statuses regardless of active status tab
  16. status_counts empty dict when no leads match common filters

Isolation strategy: each fixture generates a uuid-based phone prefix and all
count-sensitive queries pass q=prefix to avoid counting data from other tests
(the SQLite engine is session-scoped so committed rows persist across tests).
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

from app.api.internal_leads import list_leads
from app.services.conversation_state import LeadDraft
from app.services.lead_service import create_lead_from_draft, mark_lead_delivered, mark_lead_failed


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _draft(phone: str, intent: str = "ask_phone", summary: str = "") -> LeadDraft:
    return LeadDraft(
        phone=phone,
        conversation_id=str(uuid.uuid4()),
        latest_intent=intent,
        summary_hint=summary,
    )


def _create(draft: LeadDraft, db) -> object:
    with patch("app.services.lead_service._emit"):
        return create_lead_from_draft(draft, db)


def _prefix() -> str:
    """Return a unique 8-char hex prefix safe to use as a phone-number prefix."""
    return uuid.uuid4().hex[:8]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def pop(db):
    """
    5 leads, unique phone prefix, mixed statuses and intents.
    Yields (db, prefix, lead_map) so tests can filter by prefix via q=prefix.

    Lead map keys: new1, delivered, failed, new2, new3
    Status breakdown: new=3, delivered=1, failed=1
    Intent breakdown: ask_phone=3, transfer_to_human=2
    """
    p = _prefix()
    l1 = _create(_draft(f"{p}101", intent="ask_phone",        summary="أريد حجز تحليل"), db)
    l2 = _create(_draft(f"{p}102", intent="transfer_to_human",summary="أحتاج مساعدة"), db)
    l3 = _create(_draft(f"{p}103", intent="ask_phone",        summary="استفسار عن العيادة"), db)
    l4 = _create(_draft(f"{p}104", intent="ask_phone",        summary="حجز خاص"), db)
    l5 = _create(_draft(f"{p}105", intent="transfer_to_human",summary="مشكلة تقنية"), db)

    mark_lead_delivered(l2.id, db)
    mark_lead_failed(l3.id, "timeout", db)

    yield db, p, {"new1": l1, "delivered": l2, "failed": l3, "new2": l4, "new3": l5}


# ---------------------------------------------------------------------------
# 1. No filters returns all leads
# ---------------------------------------------------------------------------

def test_no_filters_returns_leads(pop):
    db, p, leads = pop
    result = list_leads(db=db)
    assert result.total >= 5
    phones = {i.phone for i in result.items}
    for lead in leads.values():
        assert lead.phone in phones


# ---------------------------------------------------------------------------
# 2. Filter by status
# ---------------------------------------------------------------------------

def test_filter_by_status_new(pop):
    db, p, leads = pop
    result = list_leads(status_filter="new", q=p, db=db)
    assert result.total == 3
    assert all(i.status == "new" for i in result.items)


def test_filter_by_status_delivered(pop):
    db, p, leads = pop
    result = list_leads(status_filter="delivered", q=p, db=db)
    assert result.total == 1
    assert result.items[0].phone == leads["delivered"].phone


def test_filter_by_status_failed(pop):
    db, p, leads = pop
    result = list_leads(status_filter="failed", q=p, db=db)
    assert result.total == 1
    assert result.items[0].phone == leads["failed"].phone


# ---------------------------------------------------------------------------
# 3. Invalid status → 400
# ---------------------------------------------------------------------------

def test_invalid_status_raises_400(pop):
    from fastapi import HTTPException
    db, p, _ = pop
    with pytest.raises(HTTPException) as exc_info:
        list_leads(status_filter="unknown_status", db=db)
    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# 4. Filter by latest_intent
# ---------------------------------------------------------------------------

def test_filter_by_latest_intent(pop):
    db, p, leads = pop
    result = list_leads(latest_intent="transfer_to_human", q=p, db=db)
    assert result.total == 2
    phones = {i.phone for i in result.items}
    assert leads["delivered"].phone in phones
    assert leads["new3"].phone in phones


def test_filter_by_intent_no_match(pop):
    db, p, _ = pop
    result = list_leads(latest_intent="offer_human_help", q=p, db=db)
    assert result.total == 0


# ---------------------------------------------------------------------------
# 5. Filter by latest_action
# ---------------------------------------------------------------------------

def test_filter_by_latest_action(pop):
    db, p, _ = pop
    # latest_action is set equal to latest_intent on creation
    result = list_leads(latest_action="ask_phone", q=p, db=db)
    assert result.total == 3


# ---------------------------------------------------------------------------
# 6. Search by phone
# ---------------------------------------------------------------------------

def test_search_by_phone_exact(pop):
    db, p, leads = pop
    result = list_leads(q=leads["new1"].phone, db=db)
    assert result.total == 1
    assert result.items[0].phone == leads["new1"].phone


def test_search_by_phone_prefix(pop):
    db, p, _ = pop
    result = list_leads(q=p, db=db)
    assert result.total == 5


def test_search_by_phone_no_match(pop):
    db, p, _ = pop
    result = list_leads(q="nomatch_zzz_" + _prefix(), db=db)
    assert result.total == 0


# ---------------------------------------------------------------------------
# 7. Search by summary_hint
# ---------------------------------------------------------------------------

def test_search_by_summary_hint(pop):
    db, p, _ = pop
    # "حجز" appears in "أريد حجز تحليل" and "حجز خاص"
    result = list_leads(q="حجز", db=db)
    assert result.total >= 2


def test_search_by_summary_partial(pop):
    db, p, leads = pop
    result = list_leads(q="مشكلة تقنية", db=db)
    assert result.total >= 1
    phones = [i.phone for i in result.items]
    assert leads["new3"].phone in phones


# ---------------------------------------------------------------------------
# 8-10. Date range
# ---------------------------------------------------------------------------

def test_date_from_includes_recent_leads(pop):
    db, p, _ = pop
    result = list_leads(date_from="2020-01-01", q=p, db=db)
    assert result.total == 5  # all 5 are recent


def test_date_to_excludes_recent_leads(pop):
    db, p, _ = pop
    result = list_leads(date_to="2020-01-01", q=p, db=db)
    assert result.total == 0  # all leads are after 2020-01-01


def test_date_range_combined_includes_all(pop):
    db, p, _ = pop
    result = list_leads(date_from="2020-01-01", date_to="2099-12-31", q=p, db=db)
    assert result.total == 5


# ---------------------------------------------------------------------------
# 11. Combined filters
# ---------------------------------------------------------------------------

def test_combined_status_and_q(pop):
    db, p, leads = pop
    result = list_leads(status_filter="new", q=p, db=db)
    assert result.total == 3


def test_combined_intent_and_summary_q(pop):
    db, p, leads = pop
    # "ask_phone" intent AND summary contains "حجز"
    result = list_leads(latest_intent="ask_phone", q="حجز", db=db)
    assert result.total >= 2


# ---------------------------------------------------------------------------
# 12-13. Invalid dates → 400
# ---------------------------------------------------------------------------

def test_invalid_date_from_raises_400(pop):
    from fastapi import HTTPException
    db, _, _ = pop
    with pytest.raises(HTTPException) as exc_info:
        list_leads(date_from="not-a-date", db=db)
    assert exc_info.value.status_code == 400
    assert "date_from" in exc_info.value.detail


def test_invalid_date_to_raises_400(pop):
    from fastapi import HTTPException
    db, _, _ = pop
    with pytest.raises(HTTPException) as exc_info:
        list_leads(date_to="32/13/2099", db=db)
    assert exc_info.value.status_code == 400
    assert "date_to" in exc_info.value.detail


def test_empty_date_string_is_ignored(pop):
    db, p, _ = pop
    result = list_leads(date_from="", date_to="", q=p, db=db)
    assert result.total == 5


# ---------------------------------------------------------------------------
# 14. Pagination with filters
# ---------------------------------------------------------------------------

def test_pagination_with_filter(pop):
    db, p, _ = pop
    r1 = list_leads(latest_intent="ask_phone", q=p, page=1, page_size=2, db=db)
    r2 = list_leads(latest_intent="ask_phone", q=p, page=2, page_size=2, db=db)
    assert r1.total == 3
    assert len(r1.items) == 2
    assert len(r2.items) == 1
    # no overlap
    ids1 = {i.id for i in r1.items}
    ids2 = {i.id for i in r2.items}
    assert ids1.isdisjoint(ids2)


# ---------------------------------------------------------------------------
# 15. status_counts always reflects all statuses regardless of active status tab
# ---------------------------------------------------------------------------

def test_status_counts_excludes_status_filter(pop):
    """
    When filtering by status=new, status_counts should still show all statuses
    (so the tab counts remain meaningful to the user).
    """
    db, p, _ = pop
    result = list_leads(status_filter="new", q=p, db=db)
    counts = result.status_counts
    assert counts.get("new", 0) == 3
    assert counts.get("delivered", 0) >= 1
    assert counts.get("failed", 0) >= 1


def test_status_counts_present_without_filter(pop):
    db, p, _ = pop
    result = list_leads(q=p, db=db)
    counts = result.status_counts
    assert isinstance(counts, dict)
    assert counts.get("new", 0) == 3
    assert counts.get("delivered", 0) == 1
    assert counts.get("failed", 0) == 1


# ---------------------------------------------------------------------------
# 16. status_counts empty when no leads match common filters
# ---------------------------------------------------------------------------

def test_status_counts_empty_on_no_match(pop):
    db, _, _ = pop
    result = list_leads(q="nomatch_xyz_" + _prefix(), db=db)
    assert result.total == 0
    assert result.status_counts == {}
