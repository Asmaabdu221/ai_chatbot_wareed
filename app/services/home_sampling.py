"""
Home-sampling (الزيارة المنزلية) conversation helpers — pure logic.

This module deliberately avoids Redis/DB/heavy imports so it can be unit
tested offline. The stateful wiring (reading/writing ConversationState and
returning replies) lives in message_service / chat and calls into here.

Three-way decision for a city the customer names while we are awaiting it:
  * "available"    — Wareed offers home sampling there.
  * "unavailable"  — looks like a place, but not in the service area.
  * "unrecognized" — could not read a city (a question, filler, punctuation).
"""

from __future__ import annotations

import re

from app.data.home_sampling_cities import check_city_availability

# Prompt appended to the home-visit FAQ answer to start the city flow.
CITY_PROMPT = (
    "أخبرني وش المنطقة اللي أنت فيها\n"
    "وأحدد لك إذا الخدمة متوفرة عندك 📍"
)

# Reply when the named city IS served (also carries the lead CTA).
def available_reply(city_name: str) -> str:
    return (
        f"✅ أبشر! خدمة الزيارة المنزلية متوفرة في {city_name} 🏠\n"
        "اكتب رقم جوالك وفريقنا يتواصل معك لتأكيد الموعد 📅"
    )


# Reply when the place is recognised but NOT served (no lead CTA).
UNAVAILABLE_REPLY = (
    "عذراً، خدمة الزيارة المنزلية غير متوفرة حالياً في منطقتك 😔\n"
    "لكن تقدر تزور أقرب فرع، أو تواصل معنا على 📞 8001221220 لآخر التحديثات"
)

# Reply when we could not read a city name (stay in the awaiting state).
UNRECOGNIZED_REPLY = (
    "ما عرفت المنطقة 😅\n"
    "ممكن تكتب اسم مدينتك بشكل أوضح؟"
)

# Tokens that mean "this is a question / filler", not a city name.
_NON_CITY_TOKENS = {
    "وش", "ايش", "كيف", "متي", "وين", "كم", "هل", "ليش", "شلون",
    "مدري", "ادري", "ما", "لا", "نعم", "اي", "ايوه", "عن",
    "ok", "اوك", "شكرا", "مرحبا", "السلام", "هلا", "تمام",
}


def _looks_like_city_name(message: str) -> bool:
    """Heuristic: does the message read like a place name rather than a question?"""
    from app.utils.arabic_normalizer import normalize

    norm = normalize((message or "").strip())
    if not norm:
        return False
    if not re.search(r"[a-z؀-ۿ]", norm):  # no Arabic/Latin letters
        return False
    tokens = norm.split()
    if any(tok in _NON_CITY_TOKENS for tok in tokens):
        return False
    if len(tokens) > 3:  # a sentence/question, not a short city phrase
        return False
    return any(len(tok) >= 3 for tok in tokens)


def classify_city(message: str) -> tuple[str, str]:
    """Return (outcome, display_name) for a city the customer named.

    outcome is one of: "available", "unavailable", "unrecognized".
    """
    available, name = check_city_availability(message)
    if available:
        return "available", name
    if _looks_like_city_name(message):
        return "unavailable", (message or "").strip()
    return "unrecognized", (message or "").strip()


def resolve_city_reply(message: str) -> tuple[str, str]:
    """Return (outcome, reply_text) for the awaiting-city turn."""
    outcome, name = classify_city(message)
    if outcome == "available":
        return outcome, available_reply(name)
    if outcome == "unavailable":
        return outcome, UNAVAILABLE_REPLY
    return outcome, UNRECOGNIZED_REPLY


def append_city_prompt(base_answer: str) -> str:
    """Append the city question to an existing home-visit answer."""
    base = (base_answer or "").strip()
    return f"{base}\n\n{CITY_PROMPT}" if base else CITY_PROMPT
