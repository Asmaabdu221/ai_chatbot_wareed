"""Deterministic detector for result-interpretation query intent."""

from __future__ import annotations

import re

from app.services.runtime.text_normalizer import normalize_arabic

_RESULT_INTENT_HINTS = (
    "نتيجتي",
    "النتيجه",
    "النتيجة",
    "فسر لي النتيجه",
    "فسر لي النتيجة",
    "تفسير نتيجه",
    "تفسير نتيجة",
    "طلعت النتيجه",
    "طلعت النتيجة",
    "result",
)

_TEST_LIKE_HINTS = (
    "تحليل",
    "تحاليل",
    "فحص",
    "test",
    "vitamin",
    "فيتامين",
    "tsh",
    "ana",
    "hba1c",
    "cbc",
    "ferritin",
    "calcitonin",
)

_NON_RESULT_BLOCK_HINTS = (
    "فرع",
    "فروع",
    "باقه",
    "باقات",
    "package",
    "سعر",
    "ارخص",
    "افضل باقه",
)

_NUMBER_RE = re.compile(r"[-+]?\d+(?:[.,]\d+)?")


def _has_number(text: str) -> bool:
    normalized = text.translate(
        str.maketrans(
            {
                "٠": "0",
                "١": "1",
                "٢": "2",
                "٣": "3",
                "٤": "4",
                "٥": "5",
                "٦": "6",
                "٧": "7",
                "٨": "8",
                "٩": "9",
            }
        )
    )
    return bool(_NUMBER_RE.search(normalized))


def looks_like_result_query(text: str) -> bool:
    query_norm = normalize_arabic(str(text or "").strip())
    if not query_norm:
        return False

    has_result_intent = any(normalize_arabic(h) in query_norm for h in _RESULT_INTENT_HINTS)
    if has_result_intent:
        return True

    if any(normalize_arabic(h) in query_norm for h in _NON_RESULT_BLOCK_HINTS):
        return False

    has_number = _has_number(text)
    has_test_like = any(normalize_arabic(h) in query_norm for h in _TEST_LIKE_HINTS)
    return bool(has_number and has_test_like)
