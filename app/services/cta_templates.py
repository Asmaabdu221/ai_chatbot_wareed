"""
Centralized CTA and system message templates — Phase 2.

All user-facing strings live here so they can be reviewed, A/B tested,
or localised in one place without hunting through business logic.

Naming convention
-----------------
  ASK_PHONE_*     — messages that ask the user for their phone number
  OFFER_*         — soft offers (no explicit phone request)
  CONFIRM_*       — confirmations after the user provides something
  CLARIFY_*       — prompts for unclear input
"""

# ---------------------------------------------------------------------------
# Phone-collection CTAs
# ---------------------------------------------------------------------------

ASK_PHONE_SALES = (
    "إذا أردت معرفة السعر الدقيق أو الحجز، تفضل أرسل رقم جوالك وسيتواصل معك فريقنا."
)

ASK_PHONE_BOOKING = (
    "لتأكيد الحجز ومتابعة موعدك، تفضل أرسل رقم جوالك."
)

ASK_PHONE_TRANSFER = (
    "لأوصلك بأحد المختصين، تفضل أرسل رقم جوالك وسنتواصل معك في أقرب وقت."
)

ASK_PHONE_DEFAULT = (
    "هل تودّ أن يتواصل معك أحد من فريقنا؟ أرسل رقم جوالك."
)

# ---------------------------------------------------------------------------
# Human-help offer (soft — no forced phone request)
# ---------------------------------------------------------------------------

OFFER_HUMAN_HELP = (
    "إذا احتجت متابعة من متخصص، أرسل رقم جوالك وسنتواصل معك."
)

# ---------------------------------------------------------------------------
# Confirmations
# ---------------------------------------------------------------------------

CONFIRM_PHONE_RECEIVED = (
    "شكراً، تم استلام رقمك. سيتواصل معك فريقنا قريباً."
)

CONFIRM_TRANSFER_READY = (
    "تم تسجيل طلبك. سيتواصل معك أحد المختصين في أقرب وقت."
)

# ---------------------------------------------------------------------------
# Phone-attempt soft rejection
# (Only shown when the message looks like a failed phone entry, NOT for topic switches)
# ---------------------------------------------------------------------------

PHONE_ATTEMPT_SOFT = (
    "إذا أردت أن نتواصل معك، تفضل أرسل رقم جوالك بصيغة صحيحة (مثل 05XXXXXXXX)، "
    "أو اسألني عن أي شيء آخر وسيسعدني المساعدة."
)

# ---------------------------------------------------------------------------
# Clarification prompts
# ---------------------------------------------------------------------------

CLARIFY_HINT = (
    "لم أفهم طلبك بوضوح — هل يمكنك توضيح ما تحتاجه؟ "
    "مثلاً: سعر تحليل، موعد، فرع قريب."
)


# ---------------------------------------------------------------------------
# Selector
# ---------------------------------------------------------------------------

def get_ask_phone_cta(intent_hint: str = "") -> str:
    """
    Return the most contextually appropriate phone-ask CTA.

    *intent_hint* is typically the ConversationDecision.reason string,
    e.g. ``"booking_keyword"``, ``"phone_required:price_route"``,
    ``"urgent_phrase:…"``.
    """
    hint = (intent_hint or "").lower()
    if any(k in hint for k in ("booking", "appointment", "حجز", "موعد")):
        return ASK_PHONE_BOOKING
    if any(k in hint for k in ("transfer", "urgent", "طوارئ")):
        return ASK_PHONE_TRANSFER
    if any(k in hint for k in ("price", "pricing", "sales", "سعر", "تكلفة")):
        return ASK_PHONE_SALES
    return ASK_PHONE_DEFAULT
