"""
Question Routing System
========================
Classifies user messages and routes them to the appropriate handler
without calling the API when a fixed response suffices (e.g. price → contact).
"""

import re
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# Contact message for price/offers (no API call)
CONTACT_RESPONSE = (
    "للاستفسار عن الأسعار يرجى التواصل مع أقرب فرع لمختبرات وريد على الرقم: 800-122-1220"
)

# Keywords (Arabic + English) that indicate a price/offer question
PRICE_KEYWORDS = [
    "سعر",
    "اسعار",
    "الأسعار",
    "أسعار",
    "كم يكلف",
    "كم التكلفة",
    "التكلفة",
    "الخصم",
    "خصم",
    "عرض",
    "عروض",
    "باقة",
    "باقات",
    "ريال",
    "جنيه",
    "تكلفة",
    "ثمن",
    "كم السعر",
    "كم سعر",
    "قيمة",
    "كم ريال",
    "كم جنيه",
    "الأرخص",
    "الأغلى",
    "مقارنة سعر",
    "مقارنة الأسعار",
    "price",
    "prices",
    "cost",
    "how much",
    "discount",
    "offer",
    "package",
    "packages",
]


def _normalize(text: str) -> str:
    """Lowercase and collapse spaces for matching."""
    if not text or not isinstance(text, str):
        return ""
    t = text.strip().lower()
    t = re.sub(r"\s+", " ", t)
    return t


def route(message: str) -> Tuple[str, Optional[str]]:
    """
    Classify the user message and optionally return a fixed response.

    Returns:
        (route_type, fixed_reply)
        - route_type: "price" | "general"
        - fixed_reply: If "price", the contact message; else None (proceed to cache/API).
    """
    normalized = _normalize(message)
    if not normalized:
        return "general", None

    for keyword in PRICE_KEYWORDS:
        if keyword in normalized:
            logger.info("Question routed to price (keyword: %s)", keyword)
            return "price", CONTACT_RESPONSE

    return "general", None


def get_price_response() -> str:
    """Return the standard response for price/offer questions."""
    return CONTACT_RESPONSE
