"""Deterministic detector for result-interpretation query intent."""

from __future__ import annotations

import logging
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
logger = logging.getLogger(__name__)

_RESULT_INTENT_HINTS_NORM = tuple(normalize_arabic(h) for h in _RESULT_INTENT_HINTS)
_TEST_LIKE_HINTS_NORM = tuple(normalize_arabic(h) for h in _TEST_LIKE_HINTS)
_NON_RESULT_BLOCK_HINTS_NORM = tuple(normalize_arabic(h) for h in _NON_RESULT_BLOCK_HINTS)


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

    # Exact phrase hit.
    if query_norm in _RESULT_INTENT_HINTS_NORM:
        details["exact_result_phrase"] = 1.2
        score += details["exact_result_phrase"]

    # Phrase containment with boundaries.
    padded = f" {query_norm} "
    boundary_hits = sum(1 for h in _RESULT_INTENT_HINTS_NORM if h and f" {h} " in padded)
    if boundary_hits:
        details["boundary_result_phrase"] = min(1.0, 0.7 + (boundary_hits - 1) * 0.1)
        score += details["boundary_result_phrase"]

    # Token overlap with result/test lexicon.
    overlap = _token_overlap(query_norm, _TEST_LIKE_HINTS_NORM + _RESULT_INTENT_HINTS_NORM)
    if overlap:
        details["token_overlap"] = min(0.8, overlap * 0.2)
        score += details["token_overlap"]

    # Strong keyword boost.
    if any(k in query_norm for k in ("النتيجه", "النتيجة", "نتيجتي", "result", "فسر")):
        details["strong_keyword"] = 0.5
        score += details["strong_keyword"]

    has_number = _has_number(raw_text)
    has_test_like = any(h in query_norm for h in _TEST_LIKE_HINTS_NORM if h)
    if has_number and has_test_like:
        details["number_and_test_like"] = 0.8
        score += details["number_and_test_like"]

    # Penalize short ambiguous queries unless strong result signals exist.
    words = [w for w in query_norm.split() if w]
    if len(words) <= 2 and details["exact_result_phrase"] == 0.0 and details["strong_keyword"] == 0.0:
        details["short_ambiguity_penalty"] = -0.35
        score += details["short_ambiguity_penalty"]

    return score, details


def looks_like_result_query(text: str) -> bool:
    query_norm = normalize_arabic(str(text or "").strip())
    if not query_norm:
        return False

    # Hard blockers remain absolute vetoes to avoid package/branch hijacking.
    blockers = [h for h in _NON_RESULT_BLOCK_HINTS_NORM if h and h in query_norm]
    if blockers:
        logger.debug(
            "results_detector blocked | query=%s | blockers=%s | decision=false",
            query_norm,
            blockers,
        )
        return False

    score, details = _score_result_intent(query_norm, str(text or ""))

    # Conservative thresholds:
    # - strong explicit intent phrases pass
    # - numeric + test-like signals must pass a higher bar
    has_explicit_result_phrase = details["exact_result_phrase"] > 0.0 or details["boundary_result_phrase"] >= 0.7
    has_number_and_test_like = details["number_and_test_like"] > 0.0
    decision = bool(
        has_explicit_result_phrase
        or (has_number_and_test_like and score >= 1.3)
        or score >= 1.6
    )

    logger.debug(
        "results_detector score | query=%s | score=%.3f | details=%s | decision=%s",
        query_norm,
        score,
        details,
        decision,
    )

    if decision:
        return True
    return False
