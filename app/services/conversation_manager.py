"""
Conversation Manager — Phase 1: deterministic action classification.

This layer sits BEFORE final response delivery and decides what kind of
follow-up action a conversation turn requires. It is:

  - Fully deterministic (no LLM, no database, no I/O).
  - Non-blocking (caller must wrap in try/except; failures are silent).
  - Read-only in Phase 1: it classifies and logs but does not yet alter
    the reply or trigger phone collection.

Architecture position
---------------------
  User message
      → route_question()     (question_router — price guard)
      → decide_conversation_action()   ← THIS MODULE
      → smart cache / RAG / OpenAI
      → ChatResponse

Decision priority (first match wins)
--------------------------------------
  1. TRANSFER_TO_HUMAN  — explicit human-agent demand or medical emergency
  2. ASK_PHONE          — booking / appointment / price follow-up
  3. OFFER_HUMAN_HELP   — results inquiry, symptom follow-up, customer service
  4. CLARIFY            — vague, too short, or no-domain-match
  5. ANSWER_ONLY        — default for informational queries

Inputs accepted
---------------
  user_text       : Raw user message (Arabic or English).
  detected_route  : Runtime route string when available, e.g. "branches",
                    "faq_only", "price_inquiry".  Pass "" if not yet known.
  runtime_source  : Source subsystem ("branches", "tests", "faq", ...).
  runtime_meta    : Structured metadata dict from the runtime result, if any.
  runtime_reply   : Final reply text if already generated (for reply-side signals).

Phase 2 roadmap
---------------
  - Wire action into response (append soft CTA to reply for OFFER_HUMAN_HELP).
  - Wire ASK_PHONE into backend lead-capture endpoint.
  - Wire TRANSFER_TO_HUMAN into real-time queue push.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Normalizer (optional — gracefully degrade when module is not on path)
# ---------------------------------------------------------------------------
try:
    from app.services.runtime.text_normalizer import normalize_arabic as _normalize_ar
except ImportError:  # pragma: no cover
    def _normalize_ar(text: str) -> str:  # type: ignore[misc]
        return text


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

class ConversationAction(str, Enum):
    """The set of conversation actions this manager can recommend."""

    ANSWER_ONLY = "ANSWER_ONLY"
    """Deliver the answer; no follow-up needed."""

    ASK_PHONE = "ASK_PHONE"
    """Collect the customer's phone number so staff can follow up."""

    OFFER_HUMAN_HELP = "OFFER_HUMAN_HELP"
    """Offer to connect the customer to a human agent (soft / optional)."""

    TRANSFER_TO_HUMAN = "TRANSFER_TO_HUMAN"
    """Flag the conversation for mandatory human handoff."""

    CLARIFY = "CLARIFY"
    """Ask the customer to clarify before the bot can proceed."""


@dataclass(frozen=True)
class ConversationDecision:
    """Immutable result object returned by :func:`decide_conversation_action`."""

    action: ConversationAction
    reason: str
    """Human-readable reason code, e.g. ``"booking_keyword"``."""

    detected_route: str
    """The runtime route string that was passed in (may be empty)."""

    confidence: str
    """``"high"``, ``"medium"``, or ``"low"`` — reflects signal strength."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Auxiliary data for downstream consumers (Phase 2 wiring)."""


# ---------------------------------------------------------------------------
# Compiled text-signal patterns
# All patterns use Arabic-primary keywords that mirror the widget's lead
# detection regexes, plus common English equivalents for robustness.
# ---------------------------------------------------------------------------

_BOOKING_RE = re.compile(
    r"حجز|موعد|booking|appointment",
    re.IGNORECASE,
)
_PRICE_RE = re.compile(
    r"سعر|أسعار|اسعار|تكلفة|price|pricing|cost",
    re.IGNORECASE,
)
_RESULTS_RE = re.compile(
    r"نتيجة|نتيجتي|نتائجي|نتائج|نتيجه|تأخرت|result|نتيجة متأخرة",
    re.IGNORECASE,
)
_SYMPTOMS_RE = re.compile(
    r"دوخة|دوخه|صداع|حمى|حرارة|ألم|الم|تعب|إرهاق|ارهاق|اعراض|أعراض"
    r"|اعاني|أعاني|ضيق تنفس|مغص|غثيان|خفقان",
    re.IGNORECASE,
)
_CUSTOMER_SERVICE_RE = re.compile(
    r"خدمة العملاء|تواصل مع|وصلني بـ|موظف|شكوى|customer service",
    re.IGNORECASE,
)
_BRANCH_RE = re.compile(
    r"فرع|فروع|موقع|وين|أقرب|عنوان|location",
    re.IGNORECASE,
)
_TEST_RE = re.compile(
    r"تحليل|تحاليل|فحص|اختبار|hba1c|tsh|cbc|فيتامين|ferritin",
    re.IGNORECASE,
)
_PACKAGE_RE = re.compile(
    r"باقة|باقه|باقات|package",
    re.IGNORECASE,
)
_GREETING_RE = re.compile(
    r"مرحبا|السلام عليكم|أهلا|اهلا|هلا|هلو|hello|hi\b",
    re.IGNORECASE,
)

# Routes from runtime_router that imply no meaningful answer was found
_NO_MATCH_ROUTES = frozenset({
    "faq_only_no_match",
    "faq_only_no_match_domains_prefilter",
    "no_runtime_mode",
    "clarify",
    "rebuild_mode",
})

# Routes from runtime_router that map directly to a ConversationAction
_ROUTE_ACTION_MAP: dict[str, ConversationAction] = {
    "greeting": ConversationAction.ANSWER_ONLY,
    "general_conversation": ConversationAction.ANSWER_ONLY,
    "faq_only": ConversationAction.ANSWER_ONLY,
    "faq_safe": ConversationAction.ANSWER_ONLY,
    "branches": ConversationAction.ANSWER_ONLY,
    "branches_city_list": ConversationAction.ANSWER_ONLY,
    "branches_detail": ConversationAction.ANSWER_ONLY,
    "packages": ConversationAction.ANSWER_ONLY,
    "packages_business": ConversationAction.ANSWER_ONLY,
    "tests": ConversationAction.ANSWER_ONLY,
    "tests_explanation": ConversationAction.ANSWER_ONLY,
    "tests_definition": ConversationAction.ANSWER_ONLY,
    "tests_business_fasting": ConversationAction.ANSWER_ONLY,
    "tests_business_preparation": ConversationAction.ANSWER_ONLY,
    "tests_business_sample_type": ConversationAction.ANSWER_ONLY,
    # Price routes trigger phone collection
    "tests_business_price": ConversationAction.ASK_PHONE,
    "price_inquiry": ConversationAction.ASK_PHONE,
    # Results / symptoms → offer human help
    "results_interpretation": ConversationAction.OFFER_HUMAN_HELP,
    "symptoms_suggestions": ConversationAction.OFFER_HUMAN_HELP,
    # Clarification routes
    "symptoms_clarification": ConversationAction.CLARIFY,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def decide_conversation_action(
    user_text: str,
    *,
    detected_route: str = "",
    runtime_source: str = "",
    runtime_meta: dict[str, Any] | None = None,
    runtime_reply: str = "",
) -> ConversationDecision:
    """Classify the conversation action required for this turn.

    Parameters
    ----------
    user_text:
        Raw user message text.
    detected_route:
        Route string from the runtime router, if available.
        Pass ``""`` when calling before routing completes.
    runtime_source:
        Source subsystem label from the runtime result
        (``"branches"``, ``"faq"``, ``"tests_business"``, …).
    runtime_meta:
        Structured metadata dict from the runtime result.
    runtime_reply:
        Final reply text, if already generated.

    Returns
    -------
    ConversationDecision
        Immutable decision object.  In Phase 1 this is used only for
        logging.  Phase 2 will wire it into response behaviour.
    """
    text = (user_text or "").strip()
    route = (detected_route or "").lower().strip()
    source = (runtime_source or "").lower().strip()
    meta = dict(runtime_meta or {})

    # Guard: empty message
    if not text:
        return ConversationDecision(
            action=ConversationAction.CLARIFY,
            reason="empty_user_text",
            detected_route=route,
            confidence="high",
        )

    # --- 1. TRANSFER_TO_HUMAN ------------------------------------------------
    transfer_reason = _check_urgent_transfer(text, route)
    if transfer_reason:
        return ConversationDecision(
            action=ConversationAction.TRANSFER_TO_HUMAN,
            reason=transfer_reason,
            detected_route=route,
            confidence="high",
            metadata={"signal": transfer_reason},
        )

    # --- 2. Route-map fast path (when a route is already known) ---------------
    if route and route in _ROUTE_ACTION_MAP:
        mapped_action = _ROUTE_ACTION_MAP[route]
        return ConversationDecision(
            action=mapped_action,
            reason=f"route_map:{route}",
            detected_route=route,
            confidence="high",
            metadata={"route": route, "source": source},
        )

    # --- 3. ASK_PHONE ---------------------------------------------------------
    phone_trigger = _check_ask_phone(text, route, source)
    if phone_trigger:
        return ConversationDecision(
            action=ConversationAction.ASK_PHONE,
            reason=f"phone_required:{phone_trigger}",
            detected_route=route,
            confidence="high" if phone_trigger in ("booking", "price_route") else "medium",
            metadata={"trigger": phone_trigger},
        )

    # --- 4. OFFER_HUMAN_HELP --------------------------------------------------
    help_reason = _check_human_help(text, route, source)
    if help_reason:
        return ConversationDecision(
            action=ConversationAction.OFFER_HUMAN_HELP,
            reason=help_reason,
            detected_route=route,
            confidence="medium",
            metadata={"offer_type": help_reason},
        )

    # --- 5. CLARIFY -----------------------------------------------------------
    if _check_clarify(text, route):
        return ConversationDecision(
            action=ConversationAction.CLARIFY,
            reason="unclear_or_no_domain_match",
            detected_route=route,
            confidence="medium",
        )

    # --- 6. ANSWER_ONLY (default) --------------------------------------------
    return ConversationDecision(
        action=ConversationAction.ANSWER_ONLY,
        reason="informational_query",
        detected_route=route,
        confidence="high",
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _check_urgent_transfer(text: str, route: str) -> str | None:
    """Return a reason string if TRANSFER_TO_HUMAN is warranted, else None."""
    norm = _normalize_ar(text).lower()
    urgent_phrases = (
        "أبغى أكلم موظف",
        "ابغى اكلم موظف",
        "وصلني بموظف",
        "أبغى إنسان يرد عليّ",
        "تواصل إنساني",
        "طوارئ",
        "ضيق تنفس شديد",
        "نزيف",
        "حالة طارئة",
        "اتصل بي الآن",
    )
    for phrase in urgent_phrases:
        if _normalize_ar(phrase).lower() in norm:
            return f"urgent_phrase:{phrase[:20]}"
            
    if _CUSTOMER_SERVICE_RE.search(text):
        return "customer_service_request"
        
    return None


def _check_ask_phone(text: str, route: str, source: str) -> str | None:
    """Return a trigger string if ASK_PHONE is warranted, else None."""
    # Explicit route signal (highest confidence)
    if route in ("price_inquiry", "tests_business_price"):
        return "price_route"
    # Booking / appointment intent
    if _BOOKING_RE.search(text):
        return "booking"
    # Price inquiry without a branch context (branch + price = show branch info, not phone)
    if _PRICE_RE.search(text) and not _BRANCH_RE.search(text):
        return "pricing"
    return None


def _check_human_help(text: str, route: str, source: str) -> str | None:
    """Return a reason string if OFFER_HUMAN_HELP is warranted, else None."""
    # Results inquiry — staff can look up the actual result
    if _RESULTS_RE.search(text):
        return "results_inquiry"
    if source == "results_engine" or "results" in route:
        return "results_route"
    # Medical symptom follow-up — doctor callback may be needed
    if _SYMPTOMS_RE.search(text):
        return "symptoms_escalation"
    if source == "symptoms_engine" or "symptom" in route:
        return "symptoms_route"
    return None


def _check_clarify(text: str, route: str) -> bool:
    """Return True when the intent is too vague to act on."""
    norm = _normalize_ar(text).lower()
    tokens = [t for t in norm.split() if t]

    # No-match route AND no domain signal in the text
    if route in _NO_MATCH_ROUTES:
        has_domain = _has_domain_signal(text)
        return not has_domain

    # Very short message (≤ 2 tokens) with no recognisable signal
    if len(tokens) <= 2:
        return not _has_any_signal(text)

    return False


def _has_domain_signal(text: str) -> bool:
    """True when text contains at least one domain keyword."""
    return any(
        pattern.search(text)
        for pattern in (
            _BRANCH_RE, _TEST_RE, _PACKAGE_RE,
            _RESULTS_RE, _SYMPTOMS_RE, _BOOKING_RE, _PRICE_RE,
        )
    )


def _has_any_signal(text: str) -> bool:
    """True when text matches any known pattern (including greetings)."""
    return any(
        pattern.search(text)
        for pattern in (
            _BOOKING_RE, _PRICE_RE, _RESULTS_RE, _SYMPTOMS_RE,
            _BRANCH_RE, _TEST_RE, _PACKAGE_RE, _GREETING_RE,
            _CUSTOMER_SERVICE_RE,
        )
    )
