"""Runtime FAQ resolver using canonicalization, loading, and deterministic matching."""

from __future__ import annotations

import re
import logging
from typing import Any

from app.services.runtime.faq_canonicalizer import (
    canonicalize_faq_query,
    is_branch_specific_query,
)
from app.services.runtime.faq_loader import load_faq_records
from app.services.runtime.faq_matcher import find_best_faq_match
from app.services.runtime.text_normalizer import normalize_arabic

logger = logging.getLogger(__name__)


def _safe_str(value: Any) -> str:
    """Convert any value to a safely stripped string."""
    return str(value or "").strip()


def _safe_list(value: Any) -> list[Any]:
    """Return value as list when possible, otherwise an empty list."""
    return value if isinstance(value, list) else []


def _escape_debug(value: Any) -> str:
    """Return unicode-escaped debug-safe text."""
    return _safe_str(value).encode("unicode_escape").decode()


def _is_privacy_style_question(user_text: str) -> bool:
    """Return True when the user question is phrased as privacy access by others."""
    user_norm = normalize_arabic(user_text)
    if not user_norm:
        return False

    triggers = (
        "هل احد",
        "هل أحد",
        "هل غيري",
        "هل احد يقدر",
        "هل احد يطلع",
        "هل احد يشوف",
        "هل غيري يقدر",
        "هل غيري يشوف",
        "هل غيري يطلع",
        "احد يقدر يشوف",
        "احد يطلع على نتيجتي",
        "غيري يقدر يشوف",
    )
    trigger_norms = [normalize_arabic(t) for t in triggers]

    return any(t and t in user_norm for t in trigger_norms)


def _strip_positive_opener(text: str) -> str:
    """Remove a leading positive opener such as نعم/أكيد/طبعاً."""
    value = _safe_str(text)
    if not value:
        return ""

    patterns = (
        r"^\s*نعم\s*[,،:\-]?\s*",
        r"^\s*أكيد\s*[,،:\-]?\s*",
        r"^\s*اكيد\s*[,،:\-]?\s*",
        r"^\s*طبعا\s*[,،:\-]?\s*",
        r"^\s*طبعاً\s*[,،:\-]?\s*",
    )

    for pattern in patterns:
        value = re.sub(pattern, "", value).strip()

    return value


def _refine_faq_answer_style(user_text: str, answer: str, concepts: list[str]) -> str:
    """Apply minimal wording refinement for privacy-style yes/no questions."""
    base = _safe_str(answer)
    if not base:
        return base

    concept_set = {_safe_str(c) for c in (concepts or [])}
    if not ({"results_privacy", "sensitive_tests_privacy"} & concept_set):
        return base

    if not _is_privacy_style_question(user_text):
        return base

    if base.startswith("لا"):
        return base

    body = _strip_positive_opener(base)
    if not body:
        return "لا"

    return f"لا، {body}"


def _build_search_texts(user_text: str) -> tuple[dict[str, Any], list[str]]:
    """Canonicalize user text and return canonical data plus search texts."""
    canon = canonicalize_faq_query(user_text)

    # Keep user-derived texts first (normalized + variants).
    # Avoid blindly injecting all canonical candidate questions because
    # low-confidence candidates can create false exact matches.
    search_texts = _unique_keep_order(
        [_safe_str(canon.get("normalized"))]
        + [_safe_str(v) for v in _safe_list(canon.get("variants"))]
    )

    # Add only high-confidence canonical question hints.
    for candidate in _safe_list(canon.get("candidates")):
        if not isinstance(candidate, dict):
            continue
        score = float(candidate.get("score") or 0.0)
        if score < 0.50:
            continue
        canonical_q = _safe_str(candidate.get("canonical_question"))
        if canonical_q:
            search_texts.append(canonical_q)

    search_texts = _unique_keep_order(search_texts)
    if not search_texts:
        fallback_text = _safe_str(user_text)
        search_texts = [fallback_text] if fallback_text else []

    return canon, search_texts


def _unique_keep_order(values: list[str]) -> list[str]:
    """Return unique non-empty strings while preserving input order."""
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = _safe_str(value)
        if not clean or clean in seen:
            continue
        seen.add(clean)
        out.append(clean)
    return out


def _pick_best_match(
    search_texts: list[str],
    faq_records: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, str]:
    """Evaluate candidate search texts and return the best FAQ match plus matched search text."""
    best_match: dict[str, Any] | None = None
    best_score = -1.0
    best_search_text = ""

    for search_text in search_texts:
        clean_text = _safe_str(search_text)
        if not clean_text:
            continue

        match = find_best_faq_match(
            clean_text,
            faq_records,
            min_score=0.78,
            min_margin=0.03,
        )
        if not match:
            continue

        score = float(match.get("score") or 0.0)

        # Early stop for exact / near-exact match
        if score >= 0.999:
            return match, clean_text

        if score > best_score:
            best_score = score
            best_match = match
            best_search_text = clean_text

    return best_match, best_search_text


def _resolve_concepts_for_match(canon: dict[str, Any], faq_id: str) -> list[str]:
    """Prefer concept(s) attached to the matched FAQ id, then fall back to canonical concepts."""
    candidates = _safe_list(canon.get("candidates"))
    matched_concepts: list[str] = []

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        if _safe_str(candidate.get("faq_id")) != faq_id:
            continue
        concept = _safe_str(candidate.get("concept"))
        if concept and concept not in matched_concepts:
            matched_concepts.append(concept)

    if matched_concepts:
        return matched_concepts

    fallback_concepts = []
    for concept in _safe_list(canon.get("concepts")):
        clean = _safe_str(concept)
        if clean and clean not in fallback_concepts:
            fallback_concepts.append(clean)

    return fallback_concepts


def _should_block_branch_faq(raw_text: str, faq_id: str) -> bool:
    """Return True when generic branches FAQ must not answer a specific location query."""
    return faq_id == "faq::10" and is_branch_specific_query(raw_text)


def resolve_faq(user_text: str) -> dict[str, Any] | None:
    """Resolve user text to a confident FAQ match, or return None."""
    raw_text = _safe_str(user_text)
    if not raw_text:
        return None

    # Hard guard in FAQ-only phase:
    # branch/location-specific queries should not resolve to generic/unrelated FAQs.
    if is_branch_specific_query(raw_text):
        logger.info(
            "FAQ_RESOLVER_DEBUG | query=%s | normalized=%s | candidate_texts=[] | selected_faq_id=none | matched_text=none | route=faq_only_no_match_branch_specific",
            _escape_debug(raw_text),
            _escape_debug(normalize_arabic(raw_text)),
        )
        print(
            "FAQ_RESOLVER_DEBUG",
            {
                "query": _escape_debug(raw_text),
                "normalized": _escape_debug(normalize_arabic(raw_text)),
                "candidate_texts": [],
                "selected_faq_id": "",
                "matched_text": "",
                "route": "faq_only_no_match_branch_specific",
            },
        )
        return None

    canon, search_texts = _build_search_texts(raw_text)
    if not search_texts:
        logger.info(
            "FAQ_RESOLVER_DEBUG | query=%s | normalized=%s | candidate_texts=[] | selected_faq_id=none | matched_text=none | route=faq_only_no_match_no_search_texts",
            _escape_debug(raw_text),
            _escape_debug(canon.get("normalized")),
        )
        return None

    faq_records = load_faq_records()
    if not faq_records:
        return None

    best, best_search_text = _pick_best_match(search_texts, faq_records)
    if not best:
        logger.info(
            "FAQ_RESOLVER_DEBUG | query=%s | normalized=%s | candidate_texts=%s | selected_faq_id=none | matched_text=none | route=faq_only_no_match",
            _escape_debug(raw_text),
            _escape_debug(canon.get("normalized")),
            [_escape_debug(x) for x in search_texts],
        )
        print(
            "FAQ_RESOLVER_DEBUG",
            {
                "query": _escape_debug(raw_text),
                "normalized": _escape_debug(canon.get("normalized")),
                "candidate_texts": [_escape_debug(x) for x in search_texts],
                "selected_faq_id": "",
                "matched_text": "",
                "route": "faq_only_no_match",
            },
        )
        return None

    record = best.get("record") or {}
    faq_id = _safe_str(record.get("id"))
    concepts = _resolve_concepts_for_match(canon, faq_id)

    # Guard: keep defensive check for generic branches FAQ too.
    if _should_block_branch_faq(raw_text, faq_id):
        logger.info(
            "FAQ_RESOLVER_DEBUG | query=%s | normalized=%s | candidate_texts=%s | selected_faq_id=%s | matched_text=%s | route=faq_only_no_match_blocked_generic_branch",
            _escape_debug(raw_text),
            _escape_debug(canon.get("normalized")),
            [_escape_debug(x) for x in search_texts],
            faq_id,
            _escape_debug(best_search_text),
        )
        return None

    answer = _refine_faq_answer_style(
        user_text=raw_text,
        answer=_safe_str(record.get("answer")),
        concepts=concepts,
    )

    result = {
        "faq_id": faq_id,
        "question": _safe_str(record.get("question")),
        "answer": answer,
        "score": float(best.get("score") or 0.0),
        "margin": float(best.get("margin") or 0.0),
        "matched_text": _safe_str(best.get("matched_text")) or best_search_text,
        "concepts": concepts,
        "canonical_candidates": [_safe_str(x) for x in search_texts if _safe_str(x)],
        "matched_via": "faq",
        "source": "faq",
    }
    logger.info(
        "FAQ_RESOLVER_DEBUG | query=%s | normalized=%s | candidate_texts=%s | selected_faq_id=%s | matched_text=%s | route=faq_only",
        _escape_debug(raw_text),
        _escape_debug(canon.get("normalized")),
        [_escape_debug(x) for x in search_texts],
        faq_id,
        _escape_debug(result.get("matched_text")),
    )
    print(
        "FAQ_RESOLVER_DEBUG",
        {
            "query": _escape_debug(raw_text),
            "normalized": _escape_debug(canon.get("normalized")),
            "candidate_texts": [_escape_debug(x) for x in search_texts],
            "selected_faq_id": faq_id,
            "matched_text": _escape_debug(result.get("matched_text")),
            "route": "faq_only",
        },
    )
    return result


def resolve_faq_answer(user_text: str) -> str | None:
    """Resolve user text and return only FAQ answer text when matched."""
    result = resolve_faq(user_text)
    if not result:
        return None

    answer = _safe_str(result.get("answer"))
    return answer or None


if __name__ == "__main__":
    samples = [
        "وش الخدمات اللي عندكم",
        "عندكم سحب من البيت",
        "متى تطلع نتيجتي",
        "هل التراكمي يحتاج صيام",
        "فيه عروض الحين",
        "هل احد يقدر يشوف نتيجتي",
        "وين اقرب فرع بالرياض",
    ]

    for text in samples:
        result = resolve_faq(text)
        print(f"INPUT: {text}")
        if not result:
            print("MATCHED FAQ ID: NONE")
            print("QUESTION: NONE")
            print("ANSWER: NONE")
            print("SCORE: 0.0")
            print("MARGIN: 0.0")
            print("MATCHED TEXT: ")
            print("CONCEPTS: []")
        else:
            print(f"MATCHED FAQ ID: {result.get('faq_id', '')}")
            print(f"QUESTION: {result.get('question', '')}")
            print(f"ANSWER: {result.get('answer', '')}")
            print(f"SCORE: {result.get('score', 0.0)}")
            print(f"MARGIN: {result.get('margin', 0.0)}")
            print(f"MATCHED TEXT: {result.get('matched_text', '')}")
            print(f"CONCEPTS: {result.get('concepts', [])}")
        print("-" * 48)
