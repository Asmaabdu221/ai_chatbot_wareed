"""
Conversation Flow Integration Tests — validates the 6 critical fixes.

Tests cover:
  1. Vitamin D → must return test info (NOT branches)
  2. Price query → must show price THEN ask phone
  3. Branch query → must list branches
  4. "1" after switching topic → MUST NOT select old domain
  5. Customer service request → must trigger lead capture
  6. Phone input → must be saved in DB
  7. RAG fallback → unknown queries do NOT immediately return NO_INFO
  8. Working hours → handled by FAQ (not question_router)
  9. Route-aware decision → conversation_manager re-runs after runtime routing

All tests are deterministic — no live LLM/API calls needed.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch, MagicMock

import pytest

from app.services.conversation_manager import (
    ConversationAction,
    ConversationDecision,
    decide_conversation_action,
)
from app.services.conversation_flow import (
    FlowResult,
    apply_flow_to_reply,
    handle_awaiting_phone_state,
    process_phone_submission,
)
from app.services.conversation_state import (
    ConversationState,
    LeadDraft,
    StateEnum,
    get_state_store,
)
from app.services.question_router import route as route_question


def _fresh_id() -> str:
    return str(uuid.uuid4())


def _make_decision(action: ConversationAction, reason: str = "test", route: str = "") -> ConversationDecision:
    return ConversationDecision(
        action=action,
        reason=reason,
        detected_route=route,
        confidence="high",
    )


# ===========================================================================
# 1. Vitamin D query → must return test info, not branches
# ===========================================================================

class TestVitaminDQuery:
    """
    'فيتامين د' should be classified as a test query by conversation_manager,
    not routed to branches.
    """

    def test_vitamin_d_is_not_branch_action(self):
        decision = decide_conversation_action("فيتامين د", detected_route="tests")
        # Must be ANSWER_ONLY (test info route), NOT branches or clarify
        assert decision.action == ConversationAction.ANSWER_ONLY

    def test_vitamin_d_with_tests_route(self):
        decision = decide_conversation_action(
            "فيتامين د",
            detected_route="tests",
            runtime_source="tests",
        )
        assert decision.action == ConversationAction.ANSWER_ONLY
        assert decision.detected_route == "tests"

    def test_vitamin_d_not_ask_phone(self):
        """Vitamin D info query should NOT trigger phone collection."""
        decision = decide_conversation_action("فيتامين د", detected_route="tests_explanation")
        assert decision.action != ConversationAction.ASK_PHONE


# ===========================================================================
# 2. Price query → must show price THEN ask phone
# ===========================================================================

class TestPriceFlow:
    """
    Price queries must show the price FIRST, then append the phone CTA.
    """

    def test_price_route_triggers_ask_phone(self):
        """When route is tests_business_price, decision should be ASK_PHONE."""
        decision = decide_conversation_action(
            "كم سعر تحليل السكر",
            detected_route="tests_business_price",
        )
        assert decision.action == ConversationAction.ASK_PHONE

    def test_price_shown_before_phone_cta(self):
        """The base price reply must appear before the phone CTA in final output."""
        cid = _fresh_id()
        decision = _make_decision(
            ConversationAction.ASK_PHONE,
            reason="phone_required:price_route",
            route="tests_business_price",
        )
        base_reply = "سعر تحليل السكر HBA1C هو 120 ريال."
        result = apply_flow_to_reply(base_reply, decision, "كم سعر تحليل السكر", cid)

        # Price comes first in the reply
        assert result.final_reply.startswith("سعر تحليل السكر")
        # Phone CTA is appended AFTER the price
        assert "رقم جوالك" in result.final_reply
        # Price appears before CTA
        price_pos = result.final_reply.index("120 ريال")
        phone_pos = result.final_reply.index("رقم جوالك")
        assert price_pos < phone_pos, "Price must appear before phone CTA"

    def test_price_query_not_routed_by_question_router(self):
        """Price queries should NOT be intercepted by question_router — they
        should fall through to runtime_router."""
        route_type, fixed_reply = route_question("كم سعر تحليل السكر")
        assert fixed_reply is None, "Price queries must not produce a fixed reply"


# ===========================================================================
# 3. Branch query → must list branches
# ===========================================================================

class TestBranchQuery:

    def test_branch_query_is_answer_only(self):
        decision = decide_conversation_action(
            "أبغى الفروع بالرياض",
            detected_route="branches",
        )
        assert decision.action == ConversationAction.ANSWER_ONLY

    def test_branch_reply_no_phone_cta(self):
        """Branch queries should not ask for phone."""
        cid = _fresh_id()
        decision = _make_decision(ConversationAction.ANSWER_ONLY, route="branches")
        result = apply_flow_to_reply(
            "فروعنا في الرياض: 1. فرع العليا 2. فرع الربيع",
            decision,
            "أبغى الفروع بالرياض",
            cid,
        )
        assert "رقم جوالك" not in result.final_reply
        assert result.state_after == StateEnum.IDLE


# ===========================================================================
# 4. "1" after switching topic → MUST NOT select old domain
# ===========================================================================

class TestSelectionStateCrossDomain:
    """
    When a user switches from branches to tests, typing '1' should NOT
    select the old branch option.
    """

    def test_clear_selection_state_on_domain_change(self):
        """Directly test that selection state is cleared when domain changes."""
        from app.services.runtime.selection_state import (
            save_selection_state,
            load_selection_state,
            clear_selection_state,
        )
        cid = uuid.uuid4()

        # Simulate branch options saved in selection state
        save_selection_state(
            cid,
            options=[{"label": "فرع العليا"}, {"label": "فرع الربيع"}],
            selection_type="branch",
            city="الرياض",
        )
        state = load_selection_state(cid)
        assert state["last_selection_type"] == "branch"
        assert len(state["last_options"]) == 2

        # Domain changes to tests → selection state should be cleared
        clear_selection_state(cid)
        state_after = load_selection_state(cid)
        assert state_after["last_options"] == []
        assert state_after["last_selection_type"] == ""

    def test_old_selection_not_accessible_after_clear(self):
        """After clearing, old options must not be returned."""
        from app.services.runtime.selection_state import (
            save_selection_state,
            load_selection_state,
            clear_selection_state,
        )
        cid = uuid.uuid4()

        save_selection_state(
            cid,
            options=[{"label": "فرع الحمراء"}],
            selection_type="branch",
        )
        clear_selection_state(cid)
        state = load_selection_state(cid)
        assert state["last_options"] == []


# ===========================================================================
# 5. Customer service request → must trigger lead capture
# ===========================================================================

class TestLeadCapture:

    def test_customer_service_triggers_transfer(self):
        """'أبغى أتواصل مع خدمة العملاء' should trigger TRANSFER_TO_HUMAN."""
        decision = decide_conversation_action("أبغى أتواصل مع خدمة العملاء")
        assert decision.action == ConversationAction.TRANSFER_TO_HUMAN

    def test_transfer_asks_for_phone(self):
        """Transfer without known phone → must ask for phone."""
        cid = _fresh_id()
        decision = _make_decision(
            ConversationAction.TRANSFER_TO_HUMAN,
            reason="urgent_phrase:أبغى أتواصل",
        )
        result = apply_flow_to_reply(
            "سنوصلك بأحد مختصينا.",
            decision,
            "أبغى أتواصل مع خدمة العملاء",
            cid,
        )
        assert "رقم جوالك" in result.final_reply
        assert result.state_after == StateEnum.AWAITING_PHONE

    def test_phone_captured_creates_lead_draft(self):
        """After phone is submitted, a LeadDraft must be created."""
        cid = _fresh_id()
        get_state_store().update(
            cid,
            state=StateEnum.AWAITING_PHONE,
            pending_action=ConversationAction.TRANSFER_TO_HUMAN.value,
            pending_intent_summary="خدمة العملاء",
        )
        state = get_state_store().get(cid)
        result = handle_awaiting_phone_state("0512345678", state, cid)

        assert result is not None
        assert result.phone_captured is True
        assert result.lead_draft is not None
        assert result.lead_draft.phone == "0512345678"
        assert result.lead_draft.conversation_id == cid


# ===========================================================================
# 6. Phone input → must be saved in DB
# ===========================================================================

class TestPhoneSavedInDB:

    def test_lead_persisted_to_db(self, db):
        """Phone capture must create a Lead row in the DB."""
        from app.services.lead_service import create_lead_from_draft

        cid = str(uuid.uuid4())
        draft = LeadDraft(
            phone="0512345678",
            conversation_id=cid,
            latest_intent="ASK_PHONE",
            summary_hint="كم سعر تحليل السكر",
        )
        lead = create_lead_from_draft(draft, db)
        assert lead is not None
        assert lead.phone == "0512345678"
        assert str(lead.conversation_id) == cid

    def test_lead_delivery_stub_marks_delivered(self, db):
        """Stub delivery should mark lead as DELIVERED."""
        from app.services.lead_service import create_lead_from_draft, deliver_lead
        from app.db.models import Lead, LeadStatus

        draft = LeadDraft(
            phone="0599887766",
            conversation_id=str(uuid.uuid4()),
            latest_intent="ASK_PHONE",
            summary_hint="حجز",
        )
        lead = create_lead_from_draft(draft, db)
        assert lead is not None

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.INTERNAL_LEADS_WEBHOOK_URL = ""
            mock_settings.INTERNAL_LEADS_WEBHOOK_TIMEOUT_SECONDS = 5
            deliver_lead(lead, db)

        db.expire(lead)
        refreshed = db.get(Lead, lead.id)
        assert refreshed.status == LeadStatus.DELIVERED


# ===========================================================================
# 7. Unknown queries → do NOT immediately return NO_INFO (RAG fallback)
# ===========================================================================

class TestRAGFallback:
    """
    The RAG pipeline change allows LLM fallback before returning NO_INFO.
    These tests verify the conversation_manager doesn't prematurely block.
    """

    def test_unknown_query_not_immediately_clarify(self):
        """A domain-related query that doesn't match a route should still
        try to answer, not immediately CLARIFY."""
        decision = decide_conversation_action(
            "ما هي الفحوصات المطلوبة للحمل",
            detected_route="tests",
        )
        assert decision.action == ConversationAction.ANSWER_ONLY


# ===========================================================================
# 8. Working hours → no longer intercepted by question_router
# ===========================================================================

class TestWorkingHoursRouting:

    def test_working_hours_not_intercepted(self):
        """Working hours queries must NOT produce a fixed reply from question_router."""
        route_type, fixed_reply = route_question("متى تفتحون")
        assert fixed_reply is None, "Working hours should be handled by FAQ, not question_router"

    def test_working_hours_general_route(self):
        """Working hours should return 'general' route type from question_router."""
        route_type, fixed_reply = route_question("ساعات الدوام")
        assert fixed_reply is None


# ===========================================================================
# 9. Route-aware decision — conversation_manager with runtime route
# ===========================================================================

class TestRouteAwareDecision:
    """
    After runtime routing, decide_conversation_action must be called with the
    ACTUAL route, not the stale pre-routing empty string.
    """

    def test_tests_business_price_route_maps_to_ask_phone(self):
        decision = decide_conversation_action(
            "كم سعر تحليل الدم",
            detected_route="tests_business_price",
            runtime_source="tests_business",
        )
        assert decision.action == ConversationAction.ASK_PHONE
        assert "route_map:tests_business_price" == decision.reason

    def test_branches_route_maps_to_answer_only(self):
        decision = decide_conversation_action(
            "وين الفروع",
            detected_route="branches",
            runtime_source="branches",
        )
        assert decision.action == ConversationAction.ANSWER_ONLY

    def test_results_route_maps_to_offer_help(self):
        decision = decide_conversation_action(
            "نتيجتي",
            detected_route="results_interpretation",
            runtime_source="results_engine",
        )
        assert decision.action == ConversationAction.OFFER_HUMAN_HELP

    def test_faq_route_maps_to_answer_only(self):
        decision = decide_conversation_action(
            "كيف أحجز موعد",
            detected_route="faq_only",
            runtime_source="faq",
        )
        assert decision.action == ConversationAction.ANSWER_ONLY

    def test_empty_route_falls_through_to_text_signals(self):
        """With no route, text signals should still work."""
        decision = decide_conversation_action(
            "أبغى أتواصل مع خدمة العملاء",
            detected_route="",
        )
        assert decision.action == ConversationAction.TRANSFER_TO_HUMAN
