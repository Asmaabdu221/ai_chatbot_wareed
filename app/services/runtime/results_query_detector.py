"""Deterministic detector for result-interpretation query intent."""

from __future__ import annotations

import logging
import re
from typing import Any

from app.services.runtime.text_normalizer import normalize_arabic

_RESULT_INTENT_HINTS = (
    "نتيجة",
    "نتيجه",
    "نتيجتي",
    "النتيجة",
    "النتيجه",
    "النتائج",
    "فسر لي النتيجة",
    "فسر لي النتيجه",
    "تفسير نتيجة",
    "تفسير نتيجه",
    "طلعت النتيجة",
    "طلعت النتيجه",
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
_STANDALONE_NUMBER_RE = re.compile(
    r"(?<![A-Za-z\u0621-\u063A\u0641-\u064A])[-+]?\d+(?:[.,]\d+)?(?![A-Za-z\u0621-\u063A\u0641-\u064A])"
)
logger = logging.getLogger(__name__)

_RESULT_INTENT_HINTS_NORM = tuple(normalize_arabic(h) for h in _RESULT_INTENT_HINTS)
_TEST_LIKE_HINTS_NORM = tuple(normalize_arabic(h) for h in _TEST_LIKE_HINTS)
_NON_RESULT_BLOCK_HINTS_NORM = tuple(normalize_arabic(h) for h in _NON_RESULT_BLOCK_HINTS)
_CANONICAL_RESULT_TOKENS_NORM = {
    normalize_arabic(v) for v in ("نتيجة", "نتيجه", "نتيجتي", "النتائج")
}


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
    return bool(_STANDALONE_NUMBER_RE.search(normalized))


def _token_overlap(query_norm: str, lexicon_norm: tuple[str, ...]) -> int:
    tokens = {t for t in query_norm.split() if t}
    if not tokens:
        return 0
    return sum(1 for token in tokens if token in lexicon_norm)


def _score_result_intent(query_norm: str, raw_text: str) -> tuple[float, dict[str, float]]:
    score = 0.0
    details: dict[str, float] = {
        "exact_result_phrase": 0.0,
        "boundary_result_phrase": 0.0,
        "token_overlap": 0.0,
        "strong_keyword": 0.0,
        "number_and_test_like": 0.0,
        "short_ambiguity_penalty": 0.0,
    }

    if query_norm in _RESULT_INTENT_HINTS_NORM:
        details["exact_result_phrase"] = 1.5
        score += details["exact_result_phrase"]

    padded = f" {query_norm} "
    boundary_hits = sum(1 for h in _RESULT_INTENT_HINTS_NORM if h and f" {h} " in padded)
    if boundary_hits:
        details["boundary_result_phrase"] = min(1.3, 1.0 + (boundary_hits - 1) * 0.1)
        score += details["boundary_result_phrase"]

    overlap = _token_overlap(query_norm, _TEST_LIKE_HINTS_NORM + _RESULT_INTENT_HINTS_NORM)
    if overlap:
        details["token_overlap"] = min(0.8, overlap * 0.2)
        score += details["token_overlap"]

    if any(
        k in query_norm
        for k in (
            "النتيجة",
            "النتيجه",
            "نتيجتي",
            "النتائج",
            "result",
            "فسر",
        )
    ):
        details["strong_keyword"] = 0.5
        score += details["strong_keyword"]

    has_number = _has_number(raw_text)
    has_test_like = any(h in query_norm for h in _TEST_LIKE_HINTS_NORM if h)
    if has_number and has_test_like:
        details["number_and_test_like"] = 0.8
        score += details["number_and_test_like"]

    words = [w for w in query_norm.split() if w]
    if (
        len(words) <= 2
        and details["exact_result_phrase"] == 0.0
        and details["strong_keyword"] == 0.0
        and not (has_number and has_test_like)
    ):
        details["short_ambiguity_penalty"] = -0.35
        score += details["short_ambiguity_penalty"]

    return score, details


def _has_explicit_result_signal(query_norm: str, details: dict[str, float]) -> bool:
    if details.get("exact_result_phrase", 0.0) > 0.0 or details.get("boundary_result_phrase", 0.0) >= 1.0:
        return True
    tokens = {t for t in query_norm.split() if t}
    if tokens & _CANONICAL_RESULT_TOKENS_NORM:
        return True
    return False


def analyze_result_query(text: str) -> dict[str, Any]:
    raw_text = str(text or "").strip()
    query_norm = normalize_arabic(raw_text)
    if not query_norm:
        return {
            "query_norm": "",
            "score": 0.0,
            "details": {},
            "decision": False,
            "strong_result_intent": False,
            "has_number": False,
            "has_test_like": False,
            "blocked": False,
            "blockers": [],
        }

    blockers = [h for h in _NON_RESULT_BLOCK_HINTS_NORM if h and h in query_norm]
    if blockers:
        logger.debug(
            "results_detector blocked | query=%s | blockers=%s | decision=false",
            query_norm,
            blockers,
        )
        return {
            "query_norm": query_norm,
            "score": 0.0,
            "details": {},
            "decision": False,
            "strong_result_intent": False,
            "has_number": _has_number(raw_text),
            "has_test_like": any(h in query_norm for h in _TEST_LIKE_HINTS_NORM if h),
            "blocked": True,
            "blockers": blockers,
        }

    score, details = _score_result_intent(query_norm, raw_text)
    has_number = _has_number(raw_text)
    has_test_like = any(h in query_norm for h in _TEST_LIKE_HINTS_NORM if h)

    has_explicit_result_phrase = _has_explicit_result_signal(query_norm, details)
    decision = bool(
        has_explicit_result_phrase
        or (has_number and has_test_like and score >= 1.0)
        or score >= 1.6
    )
    strong_result_intent = bool(
        has_explicit_result_phrase
        or (has_number and has_test_like and score >= 1.0 and len([w for w in query_norm.split() if w]) <= 4)
    )

    logger.debug(
        "results_detector score | query=%s | score=%.3f | details=%s | decision=%s | strong_intent=%s | has_number=%s | has_test_like=%s",
        query_norm,
        score,
        details,
        decision,
        strong_result_intent,
        has_number,
        has_test_like,
    )

    return {
        "query_norm": query_norm,
        "score": float(score),
        "details": details,
        "decision": decision,
        "strong_result_intent": strong_result_intent,
        "has_number": has_number,
        "has_test_like": has_test_like,
        "blocked": False,
        "blockers": [],
    }


def looks_like_result_query(text: str) -> bool:
    return bool(analyze_result_query(text).get("decision"))
