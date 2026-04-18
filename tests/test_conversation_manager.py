"""
Tests for app.services.conversation_manager (Phase 1 — deterministic only).

All cases must resolve without any I/O, database, or LLM calls.
"""

import pytest

from app.services.conversation_manager import (
    ConversationAction,
    ConversationDecision,
    decide_conversation_action,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def action(text: str, route: str = "", source: str = "") -> ConversationAction:
    return decide_conversation_action(text, detected_route=route, runtime_source=source).action


def decision(text: str, route: str = "", source: str = "") -> ConversationDecision:
    return decide_conversation_action(text, detected_route=route, runtime_source=source)


# ---------------------------------------------------------------------------
# ANSWER_ONLY
# ---------------------------------------------------------------------------

class TestAnswerOnly:
    def test_branch_query(self):
        assert action("وين فروعكم") == ConversationAction.ANSWER_ONLY

    def test_branch_route_fast_path(self):
        assert action("", route="branches") == ConversationAction.CLARIFY  # empty text → CLARIFY before route map

    def test_branch_text_no_route(self):
        assert action("أبغى أعرف الفروع القريبة") == ConversationAction.ANSWER_ONLY

    def test_hba1c_fasting_question(self):
        assert action("هل تحليل HbA1c يحتاج صيام؟") == ConversationAction.ANSWER_ONLY

    def test_greeting_hi(self):
        assert action("مرحبا") == ConversationAction.ANSWER_ONLY

    def test_greeting_hello(self):
        assert action("hello") == ConversationAction.ANSWER_ONLY

    def test_greeting_route(self):
        assert action("هلا", route="greeting") == ConversationAction.ANSWER_ONLY

    def test_faq_route(self):
        assert action("ما هو CBC؟", route="faq_only") == ConversationAction.ANSWER_ONLY

    def test_tests_explanation_route(self):
        assert action("ما معنى تحليل TSH؟", route="tests_explanation") == ConversationAction.ANSWER_ONLY

    def test_package_query(self):
        assert action("عندكم باقات فحص؟") == ConversationAction.ANSWER_ONLY

    def test_packages_route(self):
        assert action("الباقات المتاحة", route="packages") == ConversationAction.ANSWER_ONLY


# ---------------------------------------------------------------------------
# ASK_PHONE
# ---------------------------------------------------------------------------

class TestAskPhone:
    def test_price_text(self):
        assert action("أبغى سعر تحليل فيتامين د") == ConversationAction.ASK_PHONE

    def test_booking_text(self):
        assert action("أبغى أحجز موعد") == ConversationAction.ASK_PHONE

    def test_appointment_text(self):
        assert action("كيف أحجز appointment؟") == ConversationAction.ASK_PHONE

    def test_price_route_fast_path(self):
        assert action("كم سعر CBC؟", route="price_inquiry") == ConversationAction.ASK_PHONE

    def test_tests_business_price_route(self):
        assert action("الأسعار", route="tests_business_price") == ConversationAction.ASK_PHONE

    def test_cost_keyword(self):
        assert action("ما تكلفة تحليل الدهون؟") == ConversationAction.ASK_PHONE

    def test_pricing_english(self):
        assert action("what is the pricing for CBC?") == ConversationAction.ASK_PHONE

    def test_price_near_branch_stays_phone(self):
        # Price + no branch context → ASK_PHONE
        assert action("أبغى أعرف سعر الفحص") == ConversationAction.ASK_PHONE

    def test_high_confidence_on_booking(self):
        d = decision("أبغى أحجز")
        assert d.action == ConversationAction.ASK_PHONE
        assert d.confidence == "high"

    def test_high_confidence_on_price_route(self):
        d = decision("سعر التحليل", route="price_inquiry")
        assert d.confidence == "high"


# ---------------------------------------------------------------------------
# OFFER_HUMAN_HELP
# ---------------------------------------------------------------------------

class TestOfferHumanHelp:
    def test_results_text(self):
        assert action("عندي نتيجة تحليل وأبغى أفهمها") == ConversationAction.OFFER_HUMAN_HELP

    def test_delayed_results(self):
        assert action("تأخرت نتيجتي") == ConversationAction.OFFER_HUMAN_HELP

    def test_results_route(self):
        assert action("نتيجتي جاهزة؟", route="results_interpretation") == ConversationAction.OFFER_HUMAN_HELP

    def test_symptoms_text(self):
        assert action("عندي دوخة وصداع") == ConversationAction.OFFER_HUMAN_HELP

    def test_symptoms_fever(self):
        assert action("عندي حمى وتعب") == ConversationAction.OFFER_HUMAN_HELP

    def test_symptoms_route(self):
        assert action("أعاني من ألم", route="symptoms_suggestions") == ConversationAction.OFFER_HUMAN_HELP

    def test_customer_service_explicit(self):
        assert action("أبغى خدمة العملاء") == ConversationAction.OFFER_HUMAN_HELP

    def test_medium_confidence(self):
        d = decision("عندي دوخة")
        assert d.confidence == "medium"


# ---------------------------------------------------------------------------
# TRANSFER_TO_HUMAN
# ---------------------------------------------------------------------------

class TestTransferToHuman:
    def test_explicit_agent_request(self):
        assert action("أبغى أكلم موظف") == ConversationAction.TRANSFER_TO_HUMAN

    def test_connect_human(self):
        assert action("وصلني بموظف") == ConversationAction.TRANSFER_TO_HUMAN

    def test_emergency(self):
        assert action("طوارئ") == ConversationAction.TRANSFER_TO_HUMAN

    def test_severe_breathing(self):
        assert action("ضيق تنفس شديد") == ConversationAction.TRANSFER_TO_HUMAN

    def test_bleeding(self):
        assert action("نزيف") == ConversationAction.TRANSFER_TO_HUMAN

    def test_urgent_case(self):
        assert action("حالة طارئة") == ConversationAction.TRANSFER_TO_HUMAN

    def test_high_confidence(self):
        d = decision("أبغى أكلم موظف")
        assert d.confidence == "high"

    def test_transfer_beats_route_map(self):
        # Even if route suggests ANSWER_ONLY, urgent phrase wins
        assert action("أبغى أكلم موظف", route="faq_only") == ConversationAction.TRANSFER_TO_HUMAN


# ---------------------------------------------------------------------------
# CLARIFY
# ---------------------------------------------------------------------------

class TestClarify:
    def test_empty_message(self):
        assert action("") == ConversationAction.CLARIFY

    def test_whitespace_only(self):
        assert action("   ") == ConversationAction.CLARIFY

    def test_no_match_route_no_signal(self):
        assert action("شيء ما", route="faq_only_no_match") == ConversationAction.CLARIFY

    def test_very_short_no_signal(self):
        assert action("ها") == ConversationAction.CLARIFY

    def test_single_unknown_word(self):
        assert action("برتقال") == ConversationAction.CLARIFY

    def test_symptoms_clarification_route(self):
        assert action("شيء ما", route="symptoms_clarification") == ConversationAction.CLARIFY


# ---------------------------------------------------------------------------
# Edge cases — تفسير should NOT trigger OFFER_HUMAN_HELP
# ---------------------------------------------------------------------------

class TestTafserEdgeCase:
    def test_tafseer_alone_is_answer_only(self):
        # "تفسير" alone (test explanation question) must not escalate
        result = action("أبغى تفسير تحليل الكوليسترول")
        assert result != ConversationAction.OFFER_HUMAN_HELP

    def test_tafseer_with_natija_still_escalates(self):
        # "نتيجة" present → results inquiry → escalate
        assert action("أبغى تفسير نتيجة تحليلي") == ConversationAction.OFFER_HUMAN_HELP


# ---------------------------------------------------------------------------
# Return type contract
# ---------------------------------------------------------------------------

class TestReturnContract:
    def test_returns_decision_type(self):
        d = decide_conversation_action("مرحبا")
        assert isinstance(d, ConversationDecision)

    def test_action_is_enum(self):
        d = decide_conversation_action("مرحبا")
        assert isinstance(d.action, ConversationAction)

    def test_confidence_values(self):
        for text in ["", "مرحبا", "أبغى أحجز", "عندي دوخة", "أبغى أكلم موظف"]:
            d = decide_conversation_action(text)
            assert d.confidence in ("high", "medium", "low")

    def test_immutable(self):
        d = decide_conversation_action("test")
        with pytest.raises((AttributeError, TypeError)):
            d.action = ConversationAction.ANSWER_ONLY  # type: ignore[misc]
