"""Deterministic runtime resolver for test/analysis queries."""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID

from app.services.runtime.tests_disambiguation import (
    find_disambiguation_candidates,
    format_disambiguation_reply,
    set_tests_disambiguation_state,
)
from app.services.runtime.tests_description_index import find_test_description_record
from app.services.runtime.tests_business_engine import resolve_tests_business_query
from app.services.runtime.text_normalizer import normalize_arabic

TESTS_JSONL_PATH = Path("app/data/runtime/rag/tests_clean.jsonl")
logger = logging.getLogger(__name__)

_GENERAL_HINTS = (
    "تحاليل",
    "تحليل",
    "الفحوصات",
    "الفحوص",
    "الاختبارات",
    "الاختبار",
    "وش التحاليل الموجودة",
    "ايش التحاليل الموجودة",
)
_EXPLANATION_HINTS = (
    "ايش هو",
    "ما هو",
    "ماهي",
    "وش هو",
    "وش تحليل",
    "ايش تحليل",
    "ما تحليل",
    "يعني ايش",
    "وش يعني",
    "اشرح",
    "تعريف",
)
_EXPLANATION_CONTEXT_HINTS = (
    "ايش يفحص",
    "وش يفحص",
    "ما يفحص",
    "يفحص ايش",
    "يفحص وش",
    "يفيد في ايش",
    "يفيد في وش",
)
_BENEFIT_HINTS = (
    "\u0627\u064a\u0634 \u0641\u0627\u0626\u062f\u0629",
    "\u0648\u0634 \u0641\u0627\u0626\u062f\u062a\u0647",
    "\u0644\u064a\u0634 \u0646\u0633\u0648\u064a",
    "\u064a\u0641\u064a\u062f \u0641\u064a \u0627\u064a\u0634",
    "\u064a\u0641\u064a\u062f \u0641\u064a \u0648\u0634",
    "\u0641\u0627\u0626\u062f\u062a\u0647",
)
_PREPARATION_HINTS = (
    "صيام",
    "يحتاج صيام",
    "احتياج صيام",
    "تحضير",
    "التحضير",
    "قبل التحليل",
    "قبل التحليل",
    "استعداد",
    "preparation",
    "fasting",
    "استعد",
    "الاستعداد",
    "المطلوب",
    "قبل",
)
_PREPARATION_TEXT_HINTS = (
    "صيام",
    "يصام",
    "التحضير",
    "قبل التحليل",
    "قبل الفحص",
    "يفضل",
    "ينصح",
    "الاستعداد",
)
_SAMPLE_TYPE_HINTS = (
    "نوع عينة",
    "نوع العينة",
    "العينة",
    "العينه",
    "من اي عينة",
    "من أي عينة",
    "sample type",
)
_PRICE_HINTS = (
    "\u0643\u0645 \u0633\u0639\u0631",
    "\u0627\u0644\u0633\u0639\u0631",
    "\u0633\u0639\u0631",
    "\u0628\u0643\u0645",
    "\u062a\u0643\u0644\u0641\u0629",
    "price",
    "cost",
)
_GENERAL_REPLY = (
    "أقدر أساعدك بمعلومات التحاليل المتاحة. "
    "اكتب اسم التحليل بشكل مباشر (مثال: تحليل ANA) "
    "وأعرض لك التفاصيل المتوفرة."
)
_TEST_NOT_FOUND_REPLY = (
    "ما قدرت أحدد التحليل المقصود بدقة. "
    "اكتب اسم التحليل كما هو ظاهر لديك عشان أقدر أجيب التفاصيل الصحيحة."
)
_PREPARATION_NOT_AVAILABLE_REPLY = (
    "تفاصيل التحضير لهذا التحليل غير واضحة بشكل كافٍ في البيانات الحالية."
)
_DEFINITION_NOT_FOUND_REPLY = "\u0645\u0627 \u0639\u0646\u062f\u064a \u0648\u0635\u0641 \u0648\u0627\u0636\u062d \u0644\u0647\u0630\u0627 \u0627\u0644\u062a\u062d\u0644\u064a\u0644 \u0641\u064a \u0627\u0644\u0628\u064a\u0627\u0646\u0627\u062a \u0627\u0644\u062d\u0627\u0644\u064a\u0629."


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _norm(value: Any) -> str:
    return normalize_arabic(_safe_str(value))


def _as_list_of_str(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_safe_str(v) for v in value if _safe_str(v)]
    text = _safe_str(value)
    if not text:
        return []
    return [part.strip() for part in text.split(",") if part.strip()]


def _token_overlap_score(query_norm: str, hint_norm: str) -> float:
    q_tokens = {t for t in query_norm.split() if t}
    h_tokens = {t for t in hint_norm.split() if t}
    if not q_tokens or not h_tokens:
        return 0.0
    overlap = q_tokens.intersection(h_tokens)
    if not overlap:
        return 0.0
    return min(0.6, 0.25 * len(overlap))


def _detector_score(query_norm: str, hints: tuple[str, ...], strong_keywords: tuple[str, ...] = ()) -> float:
    if not query_norm:
        return 0.0

    padded = f" {query_norm} "
    score = 0.0
    for hint in hints:
        h = _norm(hint)
        if not h:
            continue
        if query_norm == h:
            score += 1.6
            continue
        if f" {h} " in padded:
            score += 1.2
        elif h in query_norm:
            score += 0.8
        score += _token_overlap_score(query_norm, h)

    strong_hits = 0
    for kw in strong_keywords:
        k = _norm(kw)
        if not k:
            continue
        if f" {k} " in padded or k in query_norm:
            score += 0.45
            strong_hits += 1

    # Ambiguity penalty for very short generic queries.
    q_tokens = [t for t in query_norm.split() if t]
    if len(q_tokens) <= 2 and strong_hits == 0:
        score -= 0.25

    return score


@lru_cache(maxsize=1)
def load_tests_records() -> list[dict[str, Any]]:
    """Load runtime test records from JSONL with normalized helper fields."""
    if not TESTS_JSONL_PATH.exists():
        return []

    rows: list[dict[str, Any]] = []
    with TESTS_JSONL_PATH.open("r", encoding="utf-8") as f:
        for raw_line in f:
            line = _safe_str(raw_line)
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue

            test_name_ar = _safe_str(obj.get("test_name_ar"))
            title = _safe_str(obj.get("title"))
            h1 = _safe_str(obj.get("h1"))
            if not (test_name_ar or title or h1):
                continue

            tags = _as_list_of_str(obj.get("tags"))
            code_tokens = _as_list_of_str(obj.get("code_tokens"))
            item = dict(obj)
            item["id"] = _safe_str(obj.get("id"))
            item["source"] = _safe_str(obj.get("source")) or "tests"
            item["test_name_ar"] = test_name_ar
            item["title"] = title
            item["h1"] = h1
            item["tags"] = tags
            item["code_tokens"] = code_tokens
            item["summary_ar"] = _safe_str(obj.get("summary_ar"))
            item["benefit_ar"] = _safe_str(obj.get("benefit_ar"))
            item["content_clean"] = _safe_str(obj.get("content_clean"))
            item["url"] = _safe_str(obj.get("url"))
            item["page_type"] = _safe_str(obj.get("page_type"))
            item["source_type"] = _safe_str(obj.get("source_type"))
            item["domain"] = _safe_str(obj.get("domain"))
            item["is_active"] = bool(obj.get("is_active", True))

            item["test_name_norm"] = _norm(test_name_ar)
            item["title_norm"] = _norm(title)
            item["h1_norm"] = _norm(h1)
            item["tags_norm"] = [_norm(t) for t in tags if _norm(t)]
            item["code_tokens_norm"] = [_norm(t) for t in code_tokens if _norm(t)]
            rows.append(item)
    return rows


def _is_general_query(query_norm: str) -> bool:
    score = _detector_score(
        query_norm,
        _GENERAL_HINTS,
        strong_keywords=("تحليل", "تحاليل", "فحص", "فحوصات", "اختبار", "اختبارات"),
    )
    decision = score >= 1.05
    if not decision:
        # Backward-compatible conservative fallback.
        decision = any(_norm(h) in query_norm for h in _GENERAL_HINTS)
    logger.debug(
        "tests_resolver general_detector | query=%s | score=%.3f | decision=%s",
        query_norm,
        score,
        decision,
    )
    return decision


def _is_general_only_query(query_norm: str) -> bool:
    """Return True when query asks for list/overview, not a specific test."""
    if not _is_general_query(query_norm):
        return False
    overview_tokens = ("الموجود", "المتوفر", "عندكم", "وش", "ايش", "عطني", "اعرض")
    overview_score = _detector_score(
        query_norm,
        overview_tokens,
        strong_keywords=("الموجود", "المتوفر", "عندكم", "اعرض", "عطني"),
    )
    decision = overview_score >= 0.60
    if not decision:
        decision = any(_norm(token) in query_norm for token in overview_tokens)
    logger.debug(
        "tests_resolver general_only_detector | query=%s | score=%.3f | decision=%s",
        query_norm,
        overview_score,
        decision,
    )
    return decision


def _is_explanation_query(query_norm: str) -> bool:
    primary_score = _detector_score(
        query_norm,
        _EXPLANATION_HINTS,
        strong_keywords=("اشرح", "تعريف", "يعني", "ماهو", "ايش هو", "وش هو"),
    )
    if primary_score >= 1.0:
        logger.debug(
            "tests_resolver explanation_detector | query=%s | primary_score=%.3f | context_score=0.000 | decision=true | reason=primary",
            query_norm,
            primary_score,
        )
        return True
    has_test_context = any(token in query_norm for token in ("تحليل", "تحاليل", "فحص", "اختبار"))
    if not has_test_context:
        logger.debug(
            "tests_resolver explanation_detector | query=%s | primary_score=%.3f | context_score=0.000 | decision=false | reason=no_test_context",
            query_norm,
            primary_score,
        )
        return False
    context_score = _detector_score(
        query_norm,
        _EXPLANATION_CONTEXT_HINTS,
        strong_keywords=("يفحص", "يفيد"),
    )
    decision = context_score >= 0.75
    if not decision:
        decision = any(_norm(h) in query_norm for h in _EXPLANATION_CONTEXT_HINTS)
    logger.debug(
        "tests_resolver explanation_detector | query=%s | primary_score=%.3f | context_score=%.3f | decision=%s",
        query_norm,
        primary_score,
        context_score,
        decision,
    )
    return decision


def _is_benefit_query(query_norm: str) -> bool:
    score = _detector_score(
        query_norm,
        _BENEFIT_HINTS,
        strong_keywords=(
            "\u0641\u0627\u0626\u062f\u0629",
            "\u0641\u0627\u0626\u062f\u062a\u0647",
            "\u0644\u064a\u0634 \u0646\u0633\u0648\u064a",
            "\u064a\u0641\u064a\u062f",
        ),
    )
    explicit_phrase = any(_norm(h) in query_norm for h in _BENEFIT_HINTS)
    has_benefit_keyword = ("\u0641\u0627\u0626\u062f" in query_norm) or ("\u064a\u0641\u064a\u062f" in query_norm)
    decision = explicit_phrase or (score >= 1.05 and has_benefit_keyword)
    logger.debug(
        "tests_resolver benefit_detector | query=%s | score=%.3f | decision=%s",
        query_norm,
        score,
        decision,
    )
    return decision


def _is_preparation_query(query_norm: str) -> bool:
    primary_score = _detector_score(
        query_norm,
        _PREPARATION_HINTS[:-4],
        strong_keywords=("صيام", "تحضير", "preparation", "fasting", "قبل التحليل"),
    )
    if primary_score >= 1.0:
        logger.debug(
            "tests_resolver preparation_detector | query=%s | primary_score=%.3f | natural_score=0.000 | decision=true | reason=primary",
            query_norm,
            primary_score,
        )
        return True

    # Natural preparation wording should require test context to avoid over-triggering.
    has_test_context = any(token in query_norm for token in ("تحليل", "تحاليل", "فحص", "اختبار"))
    if not has_test_context:
        logger.debug(
            "tests_resolver preparation_detector | query=%s | primary_score=%.3f | natural_score=0.000 | decision=false | reason=no_test_context",
            query_norm,
            primary_score,
        )
        return False
    natural_hints = ("استعد", "الاستعداد", "المطلوب", "قبل")
    natural_score = _detector_score(
        query_norm,
        natural_hints,
        strong_keywords=("استعد", "الاستعداد", "المطلوب", "قبل"),
    )
    decision = natural_score >= 0.85
    if not decision:
        decision = any(_norm(h) in query_norm for h in natural_hints)
    logger.debug(
        "tests_resolver preparation_detector | query=%s | primary_score=%.3f | natural_score=%.3f | decision=%s",
        query_norm,
        primary_score,
        natural_score,
        decision,
    )
    return decision


def _is_sample_type_query(query_norm: str) -> bool:
    score = _detector_score(
        query_norm,
        _SAMPLE_TYPE_HINTS,
        strong_keywords=("عينة", "العينة", "sample", "type"),
    )
    decision = score >= 0.95
    if not decision:
        decision = any(_norm(h) in query_norm for h in _SAMPLE_TYPE_HINTS)
    logger.debug(
        "tests_resolver sample_type_detector | query=%s | score=%.3f | decision=%s",
        query_norm,
        score,
        decision,
    )
    return decision


def _is_price_query(query_norm: str) -> bool:
    score = _detector_score(
        query_norm,
        _PRICE_HINTS,
        strong_keywords=("\u0633\u0639\u0631", "\u0628\u0643\u0645", "\u062a\u0643\u0644\u0641\u0629", "price", "cost"),
    )
    has_price_hint = score >= 0.95 or any(_norm(h) in query_norm for h in _PRICE_HINTS)
    if not has_price_hint:
        logger.debug(
            "tests_resolver price_detector | query=%s | score=%.3f | decision=false | reason=no_price_hint",
            query_norm,
            score,
        )
        return False
    has_test_context = any(
        token in query_norm
        for token in (
            "\u062a\u062d\u0644\u064a\u0644",
            "\u062a\u062d\u0627\u0644\u064a\u0644",
            "\u0641\u062d\u0635",
            "\u0627\u062e\u062a\u0628\u0627\u0631",
            "hba1c",
            "tsh",
            "cbc",
            "ferritin",
            "vitamin",
            "\u0641\u064a\u062a\u0627\u0645\u064a\u0646",
            "\u062d\u062f\u064a\u062f",
        )
    )
    decision = bool(has_price_hint and has_test_context)
    logger.debug(
        "tests_resolver price_detector | query=%s | score=%.3f | has_test_context=%s | decision=%s",
        query_norm,
        score,
        has_test_context,
        decision,
    )
    return decision


def _vitamin_key(text_norm: str) -> str:
    """Extract deterministic vitamin designator key to avoid cross-vitamin drift."""
    if not text_norm:
        return ""
    if "فيتامين د" in text_norm:
        return "vit_d"
    if "فيتامين b9" in text_norm or "فيتامين b 9" in text_norm:
        return "vit_b9"
    if "فيتامين b12" in text_norm or "فيتامين b 12" in text_norm:
        return "vit_b12"
    if "فيتامين c" in text_norm:
        return "vit_c"
    return ""


def _score_test_match(query_norm: str, record: dict[str, Any]) -> float:
    if not query_norm:
        return 0.0
    scores: list[float] = []

    fields = (
        _safe_str(record.get("test_name_norm")),
        _safe_str(record.get("title_norm")),
        _safe_str(record.get("h1_norm")),
    )
    for text in fields:
        if not text:
            continue
        if query_norm == text:
            scores.append(1.0)
            continue
        if text in query_norm or query_norm in text:
            scores.append(0.90)

    for token in list(record.get("tags_norm") or []) + list(record.get("code_tokens_norm") or []):
        if not token:
            continue
        if token in query_norm:
            # Strong code/token hit such as ANA, TSH, HbA1c.
            scores.append(0.95 if len(token) >= 3 else 0.85)

    base = max(scores) if scores else 0.0

    # Conservative vitamin disambiguation:
    # reward same vitamin key, penalize mismatched vitamin key.
    q_vit = _vitamin_key(query_norm)
    if q_vit:
        record_text = " ".join(
            [
                _safe_str(record.get("test_name_norm")),
                _safe_str(record.get("title_norm")),
                _safe_str(record.get("h1_norm")),
                " ".join(record.get("tags_norm") or []),
                " ".join(record.get("code_tokens_norm") or []),
            ]
        )
        r_vit = _vitamin_key(record_text)
        if r_vit and r_vit != q_vit:
            return max(0.0, base - 0.35)
        if r_vit and r_vit == q_vit:
            return min(1.0, base + 0.08)

    return base


def _find_specific_test(query_norm: str, records: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, float]:
    best: dict[str, Any] | None = None
    best_score = 0.0
    second_best_score = 0.0
    for record in records:
        score = _score_test_match(query_norm, record)
        if score > best_score:
            second_best_score = best_score
            best = record
            best_score = score
        elif score > second_best_score:
            second_best_score = score
    if best is None or best_score < 0.72:
        return None, 0.0
    # Safety: if more than one candidate is very close, force clarification path.
    if second_best_score >= 0.72 and (best_score - second_best_score) <= 0.04:
        return None, 0.0
    return best, best_score


def _format_test_details(record: dict[str, Any]) -> str:
    name = _safe_str(record.get("title")) or _safe_str(record.get("test_name_ar"))
    summary = _safe_str(record.get("summary_ar"))
    url = _safe_str(record.get("url"))
    lines = [name]
    if summary:
        lines.append(f"الملخص: {summary}")
    if url:
        lines.append(f"الرابط: {url}")
    return "\n".join(lines)


def _format_test_explanation(record: dict[str, Any]) -> str:
    summary = _safe_str(record.get("summary_ar"))
    if summary:
        return summary
    content = _safe_str(record.get("content_clean"))
    if content:
        normalized = content.replace("\n", " ").strip()
        sentence_parts = [p.strip() for p in normalized.split(".") if p.strip()]
        if sentence_parts:
            return ". ".join(sentence_parts[:2]).strip() + "."
        return normalized[:280].rstrip()
    return _DEFINITION_NOT_FOUND_REPLY


def _format_test_benefit(record: dict[str, Any]) -> str:
    benefit = _safe_str(record.get("benefit_ar")).strip()
    if benefit:
        return "فائدة التحليل:\n" + benefit
    return _format_test_explanation(record)


def _find_description_record_for_query(
    query: str,
    specific_match: dict[str, Any] | None,
) -> dict[str, Any] | None:
    # Prefer resolved specific test identity, then fall back to raw query lookup.
    candidates = [
        _safe_str((specific_match or {}).get("test_name_ar")),
        _safe_str((specific_match or {}).get("title")),
        _safe_str((specific_match or {}).get("h1")),
        _safe_str(query),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        record = find_test_description_record(candidate)
        if record is not None:
            return record
    return None


def _format_preparation(record: dict[str, Any]) -> str:
    name = _safe_str(record.get("title")) or _safe_str(record.get("test_name_ar"))
    text = " ".join(
        [
            _safe_str(record.get("summary_ar")),
            _safe_str(record.get("content_clean")),
        ]
    )
    text_norm = _norm(text)
    if not any(_norm(h) in text_norm for h in _PREPARATION_TEXT_HINTS):
        return _PREPARATION_NOT_AVAILABLE_REPLY

    snippet = _safe_str(record.get("summary_ar")) or _safe_str(record.get("content_clean"))
    snippet = snippet[:420].rstrip()
    return f"تحضير {name}:\n{snippet}"


def _build_disambiguation_reply(query: str, conversation_id: UUID | None = None) -> str | None:
    payload = find_disambiguation_candidates(query)
    if not payload:
        return None
    candidates = _as_list_of_str(payload.get("candidate_tests"))
    if not candidates:
        return None
    set_tests_disambiguation_state(
        candidates,
        query_type="test_preparation_query",
        conversation_id=conversation_id,
    )
    lines = ["تقصد أي تحليل بالضبط؟ هذه أقرب الخيارات:"]
    for idx, name in enumerate(candidates[:5], start=1):
        lines.append(f"{idx}) {name}")
    return "\n".join(lines)


def resolve_tests_query(user_text: str, conversation_id: UUID | None = None) -> dict[str, Any]:
    """Resolve test queries deterministically from runtime tests dataset."""
    query = _safe_str(user_text)
    query_norm = _norm(query)
    if not query_norm:
        return {
            "matched": False,
            "answer": "",
            "route": "tests_no_match",
            "meta": {"query_type": "no_match", "reason": "empty_query"},
        }

    records = [r for r in load_tests_records() if bool(r.get("is_active", True))]
    if not records:
        records = load_tests_records()
    if not records:
        return {
            "matched": False,
            "answer": "",
            "route": "tests_no_match",
            "meta": {"query_type": "no_match", "reason": "tests_data_unavailable"},
        }

    general_like = _is_general_query(query_norm)
    explanation_like = _is_explanation_query(query_norm)
    benefit_like = _is_benefit_query(query_norm)
    preparation_like = _is_preparation_query(query_norm)
    sample_type_like = _is_sample_type_query(query_norm)
    price_like = _is_price_query(query_norm)
    specific_match, specific_score = _find_specific_test(query_norm, records)
    general_only = _is_general_only_query(query_norm)

    # Fallback alignment for standalone test price queries when business route is not selected upstream.
    if price_like:
        business_result = resolve_tests_business_query(query, conversation_id=conversation_id)
        business_meta = dict(business_result.get("meta") or {})
        if bool(business_result.get("matched")) and _safe_str(business_meta.get("query_type")) == "test_price_query":
            return {
                "matched": True,
                "answer": _safe_str(business_result.get("answer")),
                "route": _safe_str(business_result.get("route")) or "tests_business_price",
                "meta": business_meta,
            }

    if general_only and not explanation_like and not preparation_like:
        return {
            "matched": True,
            "answer": _GENERAL_REPLY,
            "route": "tests_general",
            "meta": {
                "query_type": "test_general",
                "tests_count": len(records),
            },
        }

    if preparation_like:
        if specific_match is None:
            disambiguation_reply = _build_disambiguation_reply(query, conversation_id)
            return {
                "matched": True,
                "answer": disambiguation_reply or _TEST_NOT_FOUND_REPLY,
                "route": "tests_preparation",
                "meta": {
                    "query_type": "test_preparation_query",
                    "matched_test_id": "",
                    "preparation_available": False,
                    "reason": "preparation_query_without_specific_test",
                    "disambiguation_used": bool(disambiguation_reply),
                },
            }
        answer = _format_preparation(specific_match)
        return {
            "matched": True,
            "answer": answer,
            "route": "tests_preparation",
            "meta": {
                "query_type": "test_preparation_query",
                "matched_test_id": _safe_str(specific_match.get("id")),
                "matched_test_name": _safe_str(specific_match.get("title")) or _safe_str(specific_match.get("test_name_ar")),
                "score": specific_score,
                "preparation_available": answer != _PREPARATION_NOT_AVAILABLE_REPLY,
            },
        }

    if sample_type_like and specific_match is None:
        disambiguation_reply = _build_disambiguation_reply(query, conversation_id)
        if disambiguation_reply:
            return {
                "matched": True,
                "answer": disambiguation_reply,
                "route": "tests_disambiguation",
                "meta": {
                    "query_type": "test_sample_type_query",
                    "disambiguation_used": True,
                },
            }

    if explanation_like or benefit_like:
        description_record = _find_description_record_for_query(query, specific_match)
    else:
        description_record = None

    if (explanation_like or benefit_like) and description_record is None:
        return {
            "matched": True,
            "answer": _DEFINITION_NOT_FOUND_REPLY,
            "route": "tests_explanation",
            "meta": {
                "query_type": "test_explanation" if explanation_like and not benefit_like else "test_benefit",
                "reason": "definition_or_benefit_without_specific_match",
            },
        }

    if (explanation_like or benefit_like) and description_record is not None:
        has_definition_marker = any(
            marker in query_norm
            for marker in (
                "\u0627\u064a\u0634 \u0647\u0648",
                "\u0645\u0627 \u0647\u0648",
                "\u0648\u0634 \u0647\u0648",
                "\u064a\u0641\u062d\u0635",
            )
        )
        if explanation_like and benefit_like and has_definition_marker:
            summary = _format_test_explanation(description_record).strip()
            benefit = _safe_str(description_record.get("benefit_ar")).strip()
            answer = summary
            if benefit:
                answer = f"{summary}\n\nفائدة التحليل:\n{benefit}".strip()
        elif benefit_like:
            answer = _format_test_benefit(description_record)
        else:
            answer = _format_test_explanation(description_record)
        return {
            "matched": True,
            "answer": answer,
            "route": "tests_explanation",
            "meta": {
                "query_type": (
                    "test_explanation_benefit"
                    if explanation_like and benefit_like
                    else ("test_benefit" if benefit_like else "test_explanation")
                ),
                "matched_test_id": _safe_str(description_record.get("id")) or _safe_str((specific_match or {}).get("id")),
                "matched_test_name": (
                    _safe_str(description_record.get("title"))
                    or _safe_str(description_record.get("test_name_ar"))
                    or _safe_str((specific_match or {}).get("title"))
                    or _safe_str((specific_match or {}).get("test_name_ar"))
                ),
                "score": (
                    float(description_record.get("_match_score"))
                    if isinstance(description_record.get("_match_score"), (int, float))
                    else specific_score
                ),
            },
        }

    if specific_match is not None:
        return {
            "matched": True,
            "answer": _format_test_details(specific_match),
            "route": "tests_specific",
            "meta": {
                "query_type": "test_specific",
                "matched_test_id": _safe_str(specific_match.get("id")),
                "matched_test_name": _safe_str(specific_match.get("title")) or _safe_str(specific_match.get("test_name_ar")),
                "score": specific_score,
            },
        }

    if general_like or ("تحليل" in query_norm or "تحاليل" in query_norm):
        disambiguation_reply = _build_disambiguation_reply(query, conversation_id)
        if disambiguation_reply:
            return {
                "matched": True,
                "answer": disambiguation_reply,
                "route": "tests_disambiguation",
                "meta": {
                    "query_type": "test_disambiguation",
                    "disambiguation_used": True,
                },
            }
        return {
            "matched": True,
            "answer": _GENERAL_REPLY,
            "route": "tests_general",
            "meta": {
                "query_type": "test_general",
                "tests_count": len(records),
            },
        }

    return {
        "matched": False,
        "answer": "",
        "route": "tests_no_match",
        "meta": {"query_type": "no_match", "reason": "not_tests_intent"},
    }


if __name__ == "__main__":
    try:
        import sys

        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    samples = [
        "وش التحاليل الموجودة",
        "تحليل ANA",
        "ايش هو تحليل ANA",
        "هل تحليل ANA يحتاج صيام",
    ]
    for text in samples:
        result = resolve_tests_query(text)
        print(f"INPUT: {text}")
        print(f"ROUTE: {result.get('route')}")
        print(f"MATCHED: {result.get('matched')}")
        print(f"META: {result.get('meta')}")
        print(f"ANSWER: {result.get('answer')}")
        print("-" * 72)
