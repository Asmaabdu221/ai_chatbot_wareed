"""
Tests for Phase 2 conversation flow:
  - phone_utils  (extraction & validation)
  - conversation_state  (store CRUD)
  - conversation_flow  (process_phone_submission, apply_flow_to_reply)

All tests are fully deterministic — no I/O, no database, no LLM calls.
Each test uses a unique conversation_id to avoid state pollution between cases.
"""

import uuid
import pytest

from app.services.phone_utils import (
    extract_phone,
    is_phone_attempt,
    is_phone_message,
    normalize_phone,
    should_exit_awaiting_phone,
)
from app.services.conversation_state import (
    ConversationState,
    LeadDraft,
    StateEnum,
    ConversationStateStore,
    get_state_store,
)
from app.services.conversation_flow import (
    FlowResult,
    apply_flow_to_reply,
    handle_awaiting_phone_state,
    process_phone_submission,
)
from app.services.conversation_manager import ConversationAction, ConversationDecision


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fresh_id() -> str:
    """Unique conversation_id per test to avoid store pollution."""
    return str(uuid.uuid4())


def make_decision(action: ConversationAction, reason: str = "test") -> ConversationDecision:
    return ConversationDecision(
        action=action,
        reason=reason,
        detected_route="",
        confidence="high",
    )


# ===========================================================================
# phone_utils
# ===========================================================================

class TestPhoneUtils:

    def test_saudi_local_05(self):
        assert extract_phone("0512345678") == "0512345678"

    def test_saudi_local_5(self):
        assert extract_phone("512345678") == "512345678"

    def test_saudi_international_plus(self):
        assert extract_phone("+966512345678") == "+966512345678"

    def test_saudi_international_00(self):
        result = extract_phone("00966512345678")
        assert result is not None
        assert "966512345678" in result

    def test_eastern_arabic_digits(self):
        result = extract_phone("٠٥١٢٣٤٥٦٧٨")  # 05١٢٣٤٥٦٧٨ in Eastern
        assert result is not None

    def test_too_short_rejected(self):
        assert extract_phone("12345") is None

    def test_four_digits_rejected(self):
        assert extract_phone("1234") is None

    def test_price_number_rejected(self):
        # "150" looks like a price, not a phone
        assert extract_phone("150") is None

    def test_year_rejected(self):
        assert extract_phone("2024") is None

    def test_long_sentence_no_phone(self):
        text = "أبغى أعرف سعر تحليل الدم الكامل من فضلك وكم يستغرق"
        assert extract_phone(text) is None

    def test_sentence_with_embedded_phone(self):
        # 8 tokens max → "رقمي 0512345678" has 2 tokens → passes
        assert extract_phone("رقمي 0512345678") == "0512345678"

    def test_is_phone_message_true(self):
        assert is_phone_message("0512345678") is True

    def test_is_phone_message_false(self):
        assert is_phone_message("أبغى أعرف الفروع") is False

    def test_normalize_phone_strips_spaces(self):
        assert normalize_phone("05 1234 5678") == "0512345678"

    def test_normalize_eastern_plus_spaces(self):
        result = normalize_phone("+٩٦٦ ٥١٢٣٤٥٦٧٨")
        assert "966" in result


# ===========================================================================
# ConversationStateStore
# ===========================================================================

class TestConversationStateStore:

    def test_fresh_state_is_idle(self):
        store = ConversationStateStore()
        s = store.get("x")
        assert s.state == StateEnum.IDLE

    def test_update_changes_state(self):
        store = ConversationStateStore()
        store.update("x", state=StateEnum.AWAITING_PHONE)
        assert store.get("x").state == StateEnum.AWAITING_PHONE

    def test_update_multiple_fields(self):
        store = ConversationStateStore()
        store.update("x", state=StateEnum.AWAITING_PHONE, pending_action="ASK_PHONE")
        s = store.get("x")
        assert s.state == StateEnum.AWAITING_PHONE
        assert s.pending_action == "ASK_PHONE"

    def test_len_counts_entries(self):
        store = ConversationStateStore()
        store.get("a")
        store.get("b")
        assert len(store) == 2

    def test_separate_conversations_are_independent(self):
        store = ConversationStateStore()
        store.update("a", state=StateEnum.AWAITING_PHONE)
        store.update("b", state=StateEnum.PHONE_RECEIVED)
        assert store.get("a").state == StateEnum.AWAITING_PHONE
        assert store.get("b").state == StateEnum.PHONE_RECEIVED


# ===========================================================================
# process_phone_submission
# ===========================================================================

class TestProcessPhoneSubmission:

    def test_captures_valid_phone(self):
        cid = fresh_id()
        get_state_store().update(
            cid,
            state=StateEnum.AWAITING_PHONE,
            pending_action=ConversationAction.ASK_PHONE.value,
        )
        state = get_state_store().get(cid)
        result = process_phone_submission("0512345678", state, cid)

        assert result is not None
        assert result.phone_captured is True
        assert result.phone == "0512345678"
        assert result.skip_pipeline is True
        assert result.state_after == StateEnum.PHONE_RECEIVED

    def test_state_updated_to_phone_received(self):
        cid = fresh_id()
        get_state_store().update(
            cid, state=StateEnum.AWAITING_PHONE,
            pending_action=ConversationAction.ASK_PHONE.value,
        )
        state = get_state_store().get(cid)
        process_phone_submission("0512345678", state, cid)
        assert get_state_store().get(cid).state == StateEnum.PHONE_RECEIVED

    def test_lead_draft_created(self):
        cid = fresh_id()
        get_state_store().update(
            cid, state=StateEnum.AWAITING_PHONE,
            pending_action=ConversationAction.ASK_PHONE.value,
        )
        state = get_state_store().get(cid)
        result = process_phone_submission("0512345678", state, cid)
        assert result.lead_draft is not None
        assert isinstance(result.lead_draft, LeadDraft)
        assert result.lead_draft.phone == "0512345678"
        assert result.lead_draft.status == "ready"

    def test_transfer_pending_goes_to_ready_for_transfer(self):
        cid = fresh_id()
        get_state_store().update(
            cid, state=StateEnum.AWAITING_PHONE,
            pending_action=ConversationAction.TRANSFER_TO_HUMAN.value,
        )
        state = get_state_store().get(cid)
        result = process_phone_submission("0512345678", state, cid)
        assert result.state_after == StateEnum.READY_FOR_TRANSFER

    def test_invalid_text_returns_none(self):
        cid = fresh_id()
        get_state_store().update(cid, state=StateEnum.AWAITING_PHONE)
        state = get_state_store().get(cid)
        assert process_phone_submission("شكراً", state, cid) is None

    def test_not_awaiting_phone_returns_none(self):
        cid = fresh_id()
        # State is IDLE — phone not expected
        state = get_state_store().get(cid)
        assert process_phone_submission("0512345678", state, cid) is None

    def test_short_number_not_accepted(self):
        cid = fresh_id()
        get_state_store().update(cid, state=StateEnum.AWAITING_PHONE)
        state = get_state_store().get(cid)
        assert process_phone_submission("1234", state, cid) is None


# ===========================================================================
# apply_flow_to_reply
# ===========================================================================

class TestApplyFlowToReply:

    def test_answer_only_no_cta(self):
        cid = fresh_id()
        decision = make_decision(ConversationAction.ANSWER_ONLY)
        result = apply_flow_to_reply("فروعنا في عدة مدن.", decision, "وين الفروع؟", cid)

        assert result.final_reply == "فروعنا في عدة مدن."
        assert result.state_after == StateEnum.IDLE

    def test_ask_phone_appends_cta(self):
        cid = fresh_id()
        decision = make_decision(ConversationAction.ASK_PHONE, "phone_required:price_route")
        result = apply_flow_to_reply("سعر CBC هو 150 ريال.", decision, "كم سعر CBC؟", cid)

        assert "150 ريال" in result.final_reply
        assert "رقم جوالك" in result.final_reply
        assert result.state_after == StateEnum.AWAITING_PHONE

    def test_ask_phone_state_becomes_awaiting(self):
        cid = fresh_id()
        decision = make_decision(ConversationAction.ASK_PHONE)
        apply_flow_to_reply("السعر 200 ريال.", decision, "السعر؟", cid)
        assert get_state_store().get(cid).state == StateEnum.AWAITING_PHONE

    def test_no_cta_spam_while_awaiting_phone(self):
        cid = fresh_id()
        get_state_store().update(
            cid, state=StateEnum.AWAITING_PHONE,
            pending_action=ConversationAction.ASK_PHONE.value,
        )
        decision = make_decision(ConversationAction.ASK_PHONE)
        result = apply_flow_to_reply("السعر 200 ريال.", decision, "السعر؟", cid)

        # CTA must NOT be repeated
        assert result.final_reply == "السعر 200 ريال."
        assert result.state_after == StateEnum.AWAITING_PHONE

    def test_offer_human_help_appends_cta(self):
        cid = fresh_id()
        decision = make_decision(ConversationAction.OFFER_HUMAN_HELP, "results_inquiry")
        result = apply_flow_to_reply("نتائجك تشير إلى...", decision, "عندي نتيجة", cid)

        assert "نتائجك تشير إلى" in result.final_reply
        assert "رقم جوالك" in result.final_reply
        assert result.state_after == StateEnum.HUMAN_HELP_OFFERED

    def test_offer_not_repeated_when_already_awaiting(self):
        cid = fresh_id()
        get_state_store().update(cid, state=StateEnum.AWAITING_PHONE)
        decision = make_decision(ConversationAction.OFFER_HUMAN_HELP)
        result = apply_flow_to_reply("يمكنني المساعدة.", decision, "أعاني من ألم", cid)
        # No extra CTA because we're already in awaiting_phone (more advanced state)
        assert result.final_reply == "يمكنني المساعدة."

    def test_transfer_without_phone_asks_for_phone(self):
        cid = fresh_id()
        decision = make_decision(ConversationAction.TRANSFER_TO_HUMAN, "urgent_phrase:أبغى أكلم موظف")
        result = apply_flow_to_reply("سأوصلك بأحد المختصين.", decision, "أبغى أكلم موظف", cid)

        assert "رقم جوالك" in result.final_reply
        assert result.state_after == StateEnum.AWAITING_PHONE
        assert get_state_store().get(cid).pending_action == ConversationAction.TRANSFER_TO_HUMAN.value

    def test_transfer_with_phone_known_goes_to_ready(self):
        cid = fresh_id()
        get_state_store().update(cid, phone="0512345678", state=StateEnum.IDLE)
        decision = make_decision(ConversationAction.TRANSFER_TO_HUMAN)
        result = apply_flow_to_reply("سأوصلك.", decision, "أبغى أكلم موظف", cid)
        assert result.state_after == StateEnum.READY_FOR_TRANSFER

    def test_clarify_no_cta(self):
        cid = fresh_id()
        decision = make_decision(ConversationAction.CLARIFY, "unclear_or_no_domain_match")
        result = apply_flow_to_reply("لم أفهم طلبك.", decision, "برتقال", cid)
        assert result.final_reply == "لم أفهم طلبك."
        assert result.state_after == StateEnum.IDLE

    def test_state_before_matches_initial(self):
        cid = fresh_id()
        decision = make_decision(ConversationAction.ANSWER_ONLY)
        result = apply_flow_to_reply("الفروع هنا.", decision, "وين الفروع؟", cid)
        assert result.state_before == StateEnum.IDLE


# ===========================================================================
# Full scenario — end-to-end flow
# ===========================================================================

class TestEndToEndScenarios:

    def test_price_then_phone_flow(self):
        """User asks price → gets CTA → submits phone → gets confirmation."""
        cid = fresh_id()

        # Turn 1: price query
        decision = make_decision(ConversationAction.ASK_PHONE, "phone_required:price_route")
        r1 = apply_flow_to_reply("سعر CBC هو 150 ريال.", decision, "كم سعر CBC؟", cid)
        assert "رقم جوالك" in r1.final_reply
        assert get_state_store().get(cid).state == StateEnum.AWAITING_PHONE

        # Turn 2: phone submission
        state = get_state_store().get(cid)
        r2 = process_phone_submission("0512345678", state, cid)
        assert r2 is not None
        assert r2.phone_captured is True
        assert get_state_store().get(cid).state == StateEnum.PHONE_RECEIVED

    def test_branch_query_no_cta_no_state_change(self):
        """Branch query should not change state or add CTA."""
        cid = fresh_id()
        decision = make_decision(ConversationAction.ANSWER_ONLY)
        r = apply_flow_to_reply("فروعنا في الرياض.", decision, "وين الفروع؟", cid)
        assert r.final_reply == "فروعنا في الرياض."
        assert get_state_store().get(cid).state == StateEnum.IDLE

    def test_results_inquiry_flow(self):
        """Results query → OFFER_HUMAN_HELP → CTA appended."""
        cid = fresh_id()
        decision = make_decision(ConversationAction.OFFER_HUMAN_HELP, "results_inquiry")
        r = apply_flow_to_reply("نتائجك كذا.", decision, "عندي نتيجة", cid)
        assert "رقم جوالك" in r.final_reply
        assert r.state_after == StateEnum.HUMAN_HELP_OFFERED

    def test_invalid_number_not_captured(self):
        """A message that looks like text, not a phone, stays in awaiting_phone."""
        cid = fresh_id()
        get_state_store().update(cid, state=StateEnum.AWAITING_PHONE)
        state = get_state_store().get(cid)
        result = process_phone_submission("أبغى أعرف السعر", state, cid)
        assert result is None
        assert get_state_store().get(cid).state == StateEnum.AWAITING_PHONE


# ===========================================================================
# is_phone_attempt — distinguishes numeric attempts from real messages
# ===========================================================================

class TestIsPhoneAttempt:

    # --- should be True (failed phone attempts) ---
    def test_053_is_attempt(self):
        assert is_phone_attempt("053") is True

    def test_12345_is_attempt(self):
        assert is_phone_attempt("12345") is True

    def test_0567_is_attempt(self):
        assert is_phone_attempt("0567") is True

    def test_valid_phone_also_is_attempt(self):
        # A valid phone passes too — but extract_phone() catches it first
        assert is_phone_attempt("0512345678") is True

    def test_plus_digits_is_attempt(self):
        assert is_phone_attempt("+966") is True

    # --- should be False (real messages) ---
    def test_arabic_branch_query_not_attempt(self):
        assert is_phone_attempt("وين الفروع؟") is False

    def test_arabic_results_query_not_attempt(self):
        assert is_phone_attempt("عندي نتيجة تحليل") is False

    def test_arabic_customer_service_not_attempt(self):
        assert is_phone_attempt("أبغى خدمة العملاء") is False

    def test_english_sentence_not_attempt(self):
        assert is_phone_attempt("where are your branches") is False

    def test_arabic_with_number_not_attempt(self):
        # "الفرع رقم 5" — Arabic text present → not a phone attempt
        assert is_phone_attempt("الفرع رقم 5") is False

    def test_empty_string_not_attempt(self):
        assert is_phone_attempt("") is False

    def test_no_digits_not_attempt(self):
        assert is_phone_attempt("مرحبا") is False


# ===========================================================================
# should_exit_awaiting_phone
# ===========================================================================

class TestShouldExitAwaitingPhone:

    def test_branch_query_exits(self):
        assert should_exit_awaiting_phone("وين الفروع؟") is True

    def test_results_query_exits(self):
        assert should_exit_awaiting_phone("عندي نتيجة تحليل") is True

    def test_customer_service_exits(self):
        assert should_exit_awaiting_phone("أبغى خدمة العملاء") is True

    def test_valid_phone_does_not_exit(self):
        assert should_exit_awaiting_phone("0512345678") is False

    def test_phone_attempt_does_not_exit(self):
        assert should_exit_awaiting_phone("053") is False

    def test_short_numeric_does_not_exit(self):
        assert should_exit_awaiting_phone("12345") is False


# ===========================================================================
# handle_awaiting_phone_state — unified pre-pipeline handler
# ===========================================================================

class TestHandleAwaitingPhoneState:

    def _put_in_awaiting(self, cid: str, pending: str = "ASK_PHONE") -> ConversationState:
        get_state_store().update(
            cid,
            state=StateEnum.AWAITING_PHONE,
            pending_action=pending,
        )
        return get_state_store().get(cid)

    # --- valid phone ---
    def test_valid_phone_captured(self):
        cid = fresh_id()
        state = self._put_in_awaiting(cid)
        result = handle_awaiting_phone_state("0512345678", state, cid)
        assert result is not None
        assert result.phone_captured is True
        assert result.skip_pipeline is True
        assert get_state_store().get(cid).state == StateEnum.PHONE_RECEIVED

    # --- phone attempt (invalid) ---
    def test_053_gets_soft_message(self):
        cid = fresh_id()
        state = self._put_in_awaiting(cid)
        result = handle_awaiting_phone_state("053", state, cid)
        assert result is not None
        assert result.skip_pipeline is True
        assert result.phone_captured is False
        # State stays AWAITING_PHONE — user should try again
        assert get_state_store().get(cid).state == StateEnum.AWAITING_PHONE

    def test_12345_gets_soft_message(self):
        cid = fresh_id()
        state = self._put_in_awaiting(cid)
        result = handle_awaiting_phone_state("12345", state, cid)
        assert result is not None
        assert result.skip_pipeline is True
        assert get_state_store().get(cid).state == StateEnum.AWAITING_PHONE

    def test_soft_message_is_helpful(self):
        cid = fresh_id()
        state = self._put_in_awaiting(cid)
        result = handle_awaiting_phone_state("053", state, cid)
        # Message should mention correct format or invite other questions
        assert "05" in result.final_reply or "رقم" in result.final_reply

    # --- new intent / topic switch (THE BUG FIX) ---
    def test_branch_query_returns_none(self):
        """User asking about branches must NOT be shown an invalid phone message."""
        cid = fresh_id()
        state = self._put_in_awaiting(cid)
        result = handle_awaiting_phone_state("وين الفروع؟", state, cid)
        assert result is None  # caller should route normally

    def test_results_query_returns_none(self):
        cid = fresh_id()
        state = self._put_in_awaiting(cid)
        result = handle_awaiting_phone_state("عندي نتيجة تحليل", state, cid)
        assert result is None

    def test_customer_service_returns_none(self):
        cid = fresh_id()
        state = self._put_in_awaiting(cid)
        result = handle_awaiting_phone_state("أبغى خدمة العملاء", state, cid)
        assert result is None

    def test_state_reset_to_idle_on_topic_switch(self):
        cid = fresh_id()
        state = self._put_in_awaiting(cid)
        handle_awaiting_phone_state("وين الفروع؟", state, cid)
        assert get_state_store().get(cid).state == StateEnum.IDLE

    def test_pending_action_cleared_on_topic_switch(self):
        cid = fresh_id()
        state = self._put_in_awaiting(cid)
        handle_awaiting_phone_state("وين الفروع؟", state, cid)
        assert get_state_store().get(cid).pending_action == ""

    def test_not_in_awaiting_returns_none(self):
        cid = fresh_id()
        state = get_state_store().get(cid)  # IDLE
        result = handle_awaiting_phone_state("0512345678", state, cid)
        assert result is None

    # --- after topic switch, system can request phone again ---
    def test_can_ask_phone_again_after_topic_switch(self):
        cid = fresh_id()
        state = self._put_in_awaiting(cid)
        # Topic switch → IDLE
        handle_awaiting_phone_state("وين الفروع؟", state, cid)
        assert get_state_store().get(cid).state == StateEnum.IDLE
        # New price query should trigger ASK_PHONE CTA again
        decision = make_decision(ConversationAction.ASK_PHONE, "phone_required:price_route")
        result = apply_flow_to_reply("السعر 200 ريال.", decision, "كم السعر؟", cid)
        assert "رقم جوالك" in result.final_reply
        assert get_state_store().get(cid).state == StateEnum.AWAITING_PHONE
