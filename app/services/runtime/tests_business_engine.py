"""Deterministic business engine for test support queries."""

from __future__ import annotations

import json
import logging
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID

from app.services.runtime.tests_disambiguation import (
    find_disambiguation_candidates,
    format_disambiguation_reply,
    set_tests_disambiguation_state,
)
from app.services.runtime.selection_state import load_selection_state
from app.services.runtime.text_normalizer import normalize_arabic

TESTS_BUSINESS_JSONL_PATH = Path("app/data/runtime/rag/tests_business_clean.jsonl")
logger = logging.getLogger(__name__)

_FASTING_HINTS = (
    "صيام",
    "صايم",
    "كم ساعه الصيام",
    "كم ساعة الصيام",
    "يحتاج صيام",
    "هل يحتاج صيام",
    "fasting",
)
_PREPARATION_HINTS = (
    "تحضير",
    "التحضير",
    "استعداد",
    "استعد",
    "تجهيز",
    "تجهيزات",
    "تهيئة",
    "تهيئه",
    "قبل التحليل",
    "قبل تحليل",
    "قبل الفحص",
    "قبل فحص",
    "المطلوب",
    "لازم",
    "وش لازم",
    "ايش لازم",
    "ايش اسوي",
    "وش اسوي",
    "كيف استعد",
    "كيف أستعد",
    "كيف اتحضر",
    "كيف أتحضر",
)
_SYMPTOMS_HINTS = ("اعراض", "أعراض", "مناسب", "المناسب", "لتساقط", "لأعراض", "للاعراض")
_COMPLEMENTARY_HINTS = ("مكمله", "مكمله", "مكملة", "مكمل", "complementary")
_ALTERNATIVE_HINTS = ("بديل", "بديله", "بديلة", "alternative", "قريب من", "مشابه")
_SAMPLE_TYPE_HINTS = (
    "نوع عينه",
    "نوع العينه",
    "نوع العينة",
    "العينه",
    "العينة",
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


_NOT_CLEAR_MESSAGE = "المعلومة غير واضحة بشكل كافٍ في البيانات الحالية."
_TEST_NOT_FOUND_MESSAGE = "ما قدرت أحدد التحليل بدقة. اكتب اسم التحليل أو كوده مثل ما هو ظاهر عندك."
_FIELD_NOT_AVAILABLE_MESSAGE = "\u0627\u0644\u0645\u0639\u0644\u0648\u0645\u0629 \u063a\u064a\u0631 \u0645\u062a\u0648\u0641\u0631\u0629 \u0644\u0647\u0630\u0627 \u0627\u0644\u062a\u062d\u0644\u064a\u0644"
_TARGET_QUERY_ROUTE = {
    "test_price_query": "tests_business_price",
    "test_fasting_query": "tests_business_fasting",
    "test_preparation_query": "tests_business_preparation",
    "test_complementary_query": "tests_business_complementary",
    "test_alternative_query": "tests_business_alternative",
    "test_sample_type_query": "tests_business_sample_type",
}
_RELAXED_BUSINESS_TARGET_TYPES = {
    "test_price_query",
    "test_fasting_query",
    "test_preparation_query",
    "test_sample_type_query",
}
_RELAXED_BUSINESS_TARGET_SCORE = 0.54
_DUAL_STATE_PREFIX = "dual_intents::"


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _norm(value: Any) -> str:
    return normalize_arabic(_safe_str(value))


def _as_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_safe_str(v) for v in value if _safe_str(v)]
    text = _safe_str(value)
    return [text] if text else []


def _vitamin_key(text_norm: str) -> str:
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


def _tokenize(text: str) -> list[str]:
    n = _norm(text)
    if not n:
        return []
    return [t for t in n.split() if t]


def _normalize_business_query_aliases(query_norm: str) -> str:
    """Inject stable aliases to improve business-intent target matching."""
    q = _safe_str(query_norm)
    if not q:
        return ""
    expanded = q

    # HbA1c canonicalization.
    if any(token in expanded for token in ("hba1c", "hb a1c", "a1c", "سكر تراكمي", "السكر التراكمي")):
        if "hba1c" not in expanded:
            expanded = f"{expanded} hba1c"
        if "السكر التراكمي" not in expanded:
            expanded = f"{expanded} السكر التراكمي"
        if "الهيموغلوبين السكري" not in expanded:
            expanded = f"{expanded} الهيموغلوبين السكري"

    # Vitamin D canonicalization.
    if any(token in expanded for token in ("vit d", "vitamin d", "vit d3", "فيتامين د", "فيتامين دال", "دال")):
        if "فيتامين د" not in expanded:
            expanded = f"{expanded} فيتامين د"
        if "vitamin d" not in expanded:
            expanded = f"{expanded} vitamin d"

    return _norm(expanded)


@lru_cache(maxsize=1)
def load_tests_business_records() -> list[dict[str, Any]]:
    """Load business test records from runtime JSONL with normalized helpers."""
    if not TESTS_BUSINESS_JSONL_PATH.exists():
        return []

    rows: list[dict[str, Any]] = []
    with TESTS_BUSINESS_JSONL_PATH.open("r", encoding="utf-8") as f:
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

            name = _safe_str(obj.get("test_name_ar"))
            if not name:
                continue

            item = dict(obj)
            item["id"] = _safe_str(obj.get("id"))
            item["source"] = _safe_str(obj.get("source")) or "tests_business"
            item["test_name_ar"] = name
            item["english_name"] = _safe_str(obj.get("english_name"))
            item["code_alt_name"] = _safe_str(obj.get("code_alt_name"))
            item["matched_name"] = _safe_str(obj.get("matched_name"))
            item["category"] = _safe_str(obj.get("category"))
            item["benefit"] = _safe_str(obj.get("benefit"))
            item["price_raw"] = _safe_str(obj.get("price_raw"))
            item["sample_type"] = _safe_str(obj.get("sample_type"))
            item["preparation"] = _safe_str(obj.get("preparation"))
            item["review_issues"] = _safe_str(obj.get("review_issues"))
            item["source_row"] = obj.get("source_row")
            item["is_active"] = bool(obj.get("is_active", True))
            item["symptoms"] = _as_str_list(obj.get("symptoms"))
            item["complementary_tests"] = _as_str_list(obj.get("complementary_tests"))
            item["alternative_tests"] = _as_str_list(obj.get("alternative_tests"))
            item["test_name_norm"] = _norm(name)
            item["alias_terms"] = _as_str_list(obj.get("alias_terms"))
            item["match_terms"] = _as_str_list(obj.get("match_terms"))
            item["match_terms_norm"] = _as_str_list(obj.get("match_terms_norm"))
            if not item["match_terms_norm"]:
                fallback_terms = [name, item["english_name"], item["code_alt_name"], item["matched_name"]]
                item["match_terms_norm"] = [_norm(x) for x in fallback_terms if _norm(x)]
            item["symptoms_norm"] = _norm(" ".join(item["symptoms"]))
            rows.append(item)
    return rows


def _has_any_hint(query_norm: str, hints: tuple[str, ...]) -> bool:
    if not query_norm:
        return False
    padded = f" {query_norm} "
    for hint in hints:
        h = _norm(hint)
        if not h:
            continue
        if query_norm == h:
            return True
        if f" {h} " in padded:
            return True
        if h in query_norm:
            return True
    return False


def _score_query_type(query_norm: str, hints: tuple[str, ...], strong_keywords: tuple[str, ...]) -> float:
    if not query_norm:
        return 0.0

    score = 0.0
    padded = f" {query_norm} "
    query_tokens = set(_tokenize(query_norm))
    if not query_tokens:
        return 0.0

    for hint in hints:
        h = _norm(hint)
        if not h:
            continue
        hint_tokens = set(_tokenize(h))

        # Exact hint phrase match.
        if query_norm == h:
            score += 2.0
            continue

        # Boundary phrase containment (safer than loose substring).
        if f" {h} " in padded:
            score += 1.4
        elif h in query_norm:
            score += 0.9

        # Token-overlap support signal.
        if hint_tokens:
            overlap = query_tokens.intersection(hint_tokens)
            if overlap:
                score += min(0.8, 0.25 * len(overlap))

    # Strong keyword boost per intent.
    for key in strong_keywords:
        k = _norm(key)
        if not k:
            continue
        if f" {k} " in padded or k in query_norm:
            score += 0.45

    # Ambiguity penalty for very short/generic queries.
    if len(query_tokens) <= 2 and not any(k in query_norm for k in ("صيام", "تحضير", "عينه", "عينة", "بديل", "مكمل", "مكمله")):
        score -= 0.25

    return score


def _detect_query_type(query_norm: str) -> str:
    if not query_norm:
        return "no_match"

    scored: dict[str, float] = {
        "test_complementary_query": _score_query_type(
            query_norm,
            _COMPLEMENTARY_HINTS,
            ("مكمل", "مكمله", "مكملة", "complementary"),
        ),
        "test_price_query": _score_query_type(
            query_norm,
            _PRICE_HINTS,
            ("\u0643\u0645 \u0633\u0639\u0631", "\u0627\u0644\u0633\u0639\u0631", "\u0633\u0639\u0631", "\u0628\u0643\u0645", "\u062a\u0643\u0644\u0641\u0629", "price", "cost"),
        ),
        "test_alternative_query": _score_query_type(
            query_norm,
            _ALTERNATIVE_HINTS,
            ("بديل", "بديله", "بديلة", "alternative", "مشابه"),
        ),
        "test_sample_type_query": _score_query_type(
            query_norm,
            _SAMPLE_TYPE_HINTS,
            ("عينه", "عينة", "sample"),
        ),
        "test_fasting_query": _score_query_type(
            query_norm,
            _FASTING_HINTS,
            ("صيام", "صايم", "fasting"),
        ),
        "test_preparation_query": _score_query_type(
            query_norm,
            _PREPARATION_HINTS,
            ("تحضير", "استعداد", "لازم", "قبل"),
        ),
        "test_symptoms_query": _score_query_type(
            query_norm,
            _SYMPTOMS_HINTS,
            ("اعراض", "أعراض", "لتساقط", "مناسب"),
        ),
    }

    ranked = sorted(scored.items(), key=lambda x: x[1], reverse=True)
    best_type, best_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0
    margin = best_score - second_score

    selected = "no_match"
    fallback_reason = ""

    # Conservative selection: require signal + clear winner.
    if best_score >= 1.15 and margin >= 0.20:
        selected = best_type
    else:
        # Backward-compatible conservative fallback: previous ordered hint checks.
        if _has_any_hint(query_norm, _COMPLEMENTARY_HINTS):
            selected = "test_complementary_query"
            fallback_reason = "fallback_ordered_hints"
        elif _has_any_hint(query_norm, _PRICE_HINTS):
            selected = "test_price_query"
            fallback_reason = "fallback_ordered_hints"
        elif _has_any_hint(query_norm, _ALTERNATIVE_HINTS):
            selected = "test_alternative_query"
            fallback_reason = "fallback_ordered_hints"
        elif _has_any_hint(query_norm, _SAMPLE_TYPE_HINTS):
            selected = "test_sample_type_query"
            fallback_reason = "fallback_ordered_hints"
        elif _has_any_hint(query_norm, _FASTING_HINTS):
            selected = "test_fasting_query"
            fallback_reason = "fallback_ordered_hints"
        elif _has_any_hint(query_norm, _PREPARATION_HINTS):
            selected = "test_preparation_query"
            fallback_reason = "fallback_ordered_hints"
        elif _has_any_hint(query_norm, _SYMPTOMS_HINTS):
            selected = "test_symptoms_query"
            fallback_reason = "fallback_ordered_hints"
        else:
            selected = "no_match"
            fallback_reason = "low_or_ambiguous_score"

    logger.debug(
        "tests_business query_type_detection | query=%s | scores=%s | best=%s | best_score=%.3f | second=%.3f | margin=%.3f | selected=%s | reason=%s",
        query_norm,
        scored,
        best_type,
        best_score,
        second_score,
        margin,
        selected,
        fallback_reason or "scored_selection",
    )
    return selected


def _score_test_name_match(query_norm: str, test_name_norm: str) -> float:
    if not query_norm or not test_name_norm:
        return 0.0
    if query_norm == test_name_norm:
        return 1.0
    if test_name_norm in query_norm:
        return 0.95
    if query_norm in test_name_norm:
        return 0.80
    return SequenceMatcher(None, query_norm, test_name_norm).ratio()


def _score_record_match(query_norm: str, record: dict[str, Any]) -> float:
    terms = list(record.get("match_terms_norm") or [])
    if not terms:
        terms = [_safe_str(record.get("test_name_norm"))]

    best = 0.0
    for term in terms:
        score = _score_test_name_match(query_norm, _safe_str(term))
        if score > best:
            best = score

    q_vit = _vitamin_key(query_norm)
    if q_vit:
        record_blob = " ".join(terms)
        r_vit = _vitamin_key(record_blob)
        if r_vit and r_vit != q_vit:
            best = max(0.0, best - 0.35)
        elif r_vit and r_vit == q_vit:
            best = min(1.0, best + 0.08)
    return best


def _rank_target_candidates(query_norm: str, records: list[dict[str, Any]]) -> list[tuple[float, dict[str, Any]]]:
    candidate = _extract_test_candidate(query_norm)
    primary = _normalize_business_query_aliases(candidate or query_norm)
    query_enriched = _normalize_business_query_aliases(query_norm)

    scored: list[tuple[float, dict[str, Any]]] = []
    for r in records:
        score_primary = _score_record_match(primary, r)
        score_full = _score_record_match(query_enriched, r) * 0.7
        score = max(score_primary, score_full)
        if score <= 0.0:
            continue
        scored.append((score, r))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored


def _extract_target_tokens_for_relevance(query_norm: str) -> set[str]:
    candidate = _extract_test_candidate(query_norm)
    if not candidate:
        return set()
    return {t for t in _tokenize(candidate) if len(t) > 1 and t not in {"تحليل", "فحص", "اختبار", "عينة", "العينة", "نوع"}}


def _record_relevance_score(record: dict[str, Any], target_tokens: set[str]) -> float:
    if not target_tokens:
        return 0.0
    terms_blob = " ".join([_safe_str(record.get("test_name_norm")), " ".join(record.get("match_terms_norm") or [])]).strip()
    if not terms_blob:
        return 0.0
    hits = sum(1 for t in target_tokens if t and t in terms_blob)
    return hits / max(len(target_tokens), 1)


def _find_target_test(query_norm: str, records: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, float]:
    ranked = _rank_target_candidates(query_norm, records)
    if not ranked:
        return None, 0.0

    best_score, best = ranked[0]
    second_best_score = ranked[1][0] if len(ranked) > 1 else 0.0
    if best is None or best_score < 0.62:
        return None, 0.0
    # Safety: if more than one candidate is very close, force clarification path.
    if second_best_score >= 0.62 and (best_score - second_best_score) <= 0.04:
        return None, 0.0
    return best, best_score


def _find_symptom_matches(query_norm: str, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ignore = {"ما", "هو", "هي", "تحليل", "تحاليل", "مناسب", "المناسب", "اعراض", "اعراضه", "اعراضها"}
    query_tokens = [t for t in _tokenize(query_norm) if t not in ignore and len(t) > 1]
    if not query_tokens:
        return []

    scored: list[tuple[float, dict[str, Any]]] = []
    for r in records:
        symptoms_text = _safe_str(r.get("symptoms_norm"))
        if not symptoms_text:
            continue
        hit_count = sum(1 for t in query_tokens if t in symptoms_text)
        if hit_count <= 0:
            continue
        coverage = hit_count / max(len(query_tokens), 1)
        ratio = SequenceMatcher(None, query_norm, symptoms_text).ratio()
        score = (0.7 * coverage) + (0.3 * ratio)
        if coverage < 0.45:
            continue
        scored.append((score, r))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored[:5]]


def _extract_test_candidate(query_norm: str) -> str:
    """Extract likely target test phrase from the user query."""
    if not query_norm:
        return ""
    text = _normalize_business_query_aliases(query_norm)
    marker_patterns = (
        "تحليل",
        "فحص",
        "اختبار",
        "قبل تحليل",
        "قبل الفحص",
        "نوع عينة",
        "نوع العينة",
    )
    for marker in marker_patterns:
        m = _norm(marker)
        if m and m in text:
            tail = text.split(m, 1)[1].strip()
            if tail:
                return _clean_candidate_phrase(tail)
    for marker in ("تحليل", "فحص", "اختبار"):
        if marker in text:
            tail = text.split(marker, 1)[1].strip()
            if tail:
                return _clean_candidate_phrase(tail)
    return _clean_candidate_phrase(text)


def _clean_candidate_phrase(text: str) -> str:
    text_norm = _normalize_business_query_aliases(text)
    tokens = _tokenize(text_norm)
    if not tokens:
        return ""
    drop = {
        "\u0633\u0639\u0631",
        "\u0627\u0644\u0633\u0639\u0631",
        "\u0628\u0643\u0645",
        "\u062a\u0643\u0644\u0641\u0629",
        "price",
        "cost",
        "هل",
        "كم",
        "ساعه",
        "ساعة",
        "تحليل",
        "تحاليل",
        "التحاليل",
        "فحص",
        "الفحص",
        "اختبار",
        "الاختبار",
        "صيام",
        "يحتاج",
        "المطلوب",
        "ايش",
        "ما",
        "هو",
        "هي",
        "نوع",
        "عينه",
        "العينه",
        "المكمله",
        "المكملة",
        "البديل",
        "المناسبه",
        "المناسبة",
        "قبل",
        "قريب",
        "مشابه",
        "من",
        "كيف",
        "استعد",
        "لا",
        "يحتاج",
        "الصيام",
        "احتياج",
        "محتاج",
        "عينة",
        "عينه",
        "اي",
        "أي",
        "قبل",
        "بعد",
        "التحضير",
        "تحضير",
        "يلزم",
        "مطلوب",
    }
    out: list[str] = []
    for token in tokens:
        t = token
        if t.startswith("ل") and len(t) > 3:
            t = t[1:]
        if t in drop:
            continue
        out.append(t)

    code_like = [t for t in out if any(ch.isascii() for ch in t)]
    base = " ".join(code_like[:3]).strip() if code_like else " ".join(out[:5]).strip()
    if not base:
        return ""

    # Keep deterministic alias augmentation for common user forms.
    if any(t in base for t in ("hba1c", "a1c", "hb a1c")):
        base = f"{base} السكر التراكمي الهيموغلوبين السكري"
    if "فيتامين" in base and ("د" in base or "vitamin d" in base or "vit d" in base):
        if "فيتامين د" not in base:
            base = f"{base} فيتامين د"
    return _norm(base)


def _format_target_field(title: str, test_name: str, value: str) -> str:
    return f"{title} {test_name}:\n{value}"


def _encode_dual_state_query_type(primary_query_type: str, intents: dict[str, bool]) -> str:
    flags: list[str] = []
    if intents.get("price"):
        flags.append("price")
    if intents.get("fasting_or_preparation"):
        flags.append("prep")
    if intents.get("sample_type"):
        flags.append("sample")
    if not flags:
        return _safe_str(primary_query_type)
    return f"{_DUAL_STATE_PREFIX}{_safe_str(primary_query_type)}|{','.join(flags)}"


def _decode_dual_state_query_type(state_query_type: str) -> tuple[str, dict[str, bool]]:
    raw = _safe_str(state_query_type)
    if not raw.startswith(_DUAL_STATE_PREFIX):
        return raw, {"price": False, "fasting_or_preparation": False, "sample_type": False}
    payload = raw[len(_DUAL_STATE_PREFIX):]
    if "|" in payload:
        primary, flags_blob = payload.split("|", 1)
    else:
        primary, flags_blob = payload, ""
    flags = {f.strip() for f in flags_blob.split(",") if f.strip()}
    return _safe_str(primary), {
        "price": "price" in flags,
        "fasting_or_preparation": "prep" in flags,
        "sample_type": "sample" in flags,
    }


def _load_preserved_dual_intents(conversation_id: UUID | None) -> tuple[str, dict[str, bool]]:
    if conversation_id is None:
        return "", {"price": False, "fasting_or_preparation": False, "sample_type": False}
    state = load_selection_state(conversation_id)
    if _safe_str(state.get("last_selection_type")) != "test":
        return "", {"price": False, "fasting_or_preparation": False, "sample_type": False}
    state_query_type = _safe_str(state.get("query_type"))
    return _decode_dual_state_query_type(state_query_type)


def _likely_selection_label_query(query_norm: str) -> bool:
    if not query_norm:
        return False
    tokens = _tokenize(query_norm)
    if not tokens or len(tokens) > 6:
        return False
    if _has_any_hint(query_norm, _PRICE_HINTS):
        return False
    if _has_any_hint(query_norm, _FASTING_HINTS) or _has_any_hint(query_norm, _PREPARATION_HINTS):
        return False
    if _has_any_hint(query_norm, _SAMPLE_TYPE_HINTS):
        return False
    return True


def _detect_supported_dual_intents(query_norm: str) -> dict[str, bool]:
    if not query_norm:
        return {"price": False, "fasting_or_preparation": False, "sample_type": False}
    has_price = _has_any_hint(query_norm, _PRICE_HINTS)
    has_fasting = _has_any_hint(query_norm, _FASTING_HINTS)
    has_preparation = _has_any_hint(query_norm, _PREPARATION_HINTS)
    has_sample_type = _has_any_hint(query_norm, _SAMPLE_TYPE_HINTS)
    return {
        "price": bool(has_price),
        "fasting_or_preparation": bool(has_fasting or has_preparation),
        "sample_type": bool(has_sample_type),
    }


def _format_dual_intent_composed_answer(
    query_norm: str,
    target: dict[str, Any],
    *,
    intents_override: dict[str, bool] | None = None,
) -> str:
    test_name = _safe_str(target.get("test_name_ar"))
    intents = intents_override or _detect_supported_dual_intents(query_norm)
    prep_text = _safe_str(target.get("preparation"))
    sample_type = _safe_str(target.get("sample_type"))
    price_raw = _safe_str(target.get("price_raw"))

    lines: list[str] = [f"\u0645\u0639\u0644\u0648\u0645\u0627\u062a {test_name}:"]

    if intents["price"]:
        price_value = price_raw if price_raw else _FIELD_NOT_AVAILABLE_MESSAGE
        lines.append(f"1) \u0627\u0644\u0633\u0639\u0631: {price_value}")

    if intents["fasting_or_preparation"]:
        prep_value = prep_text if prep_text else _FIELD_NOT_AVAILABLE_MESSAGE
        lines.append(f"2) \u0627\u0644\u062a\u062d\u0636\u064a\u0631/\u0627\u0644\u0635\u064a\u0627\u0645: {prep_value}")

    if intents["sample_type"]:
        sample_value = sample_type if sample_type else _FIELD_NOT_AVAILABLE_MESSAGE
        lines.append(f"3) \u0646\u0648\u0639 \u0627\u0644\u0639\u064a\u0646\u0629: {sample_value}")

    return "\n".join(lines)


def _build_disambiguation_reply(
    query: str,
    query_type: str,
    state_query_type: str = "",
    conversation_id: UUID | None = None,
) -> str | None:
    payload = find_disambiguation_candidates(query)
    if not payload:
        return None
    candidates = _as_str_list(payload.get("candidate_tests"))
    if not candidates:
        return None
    set_tests_disambiguation_state(
        candidates,
        query_type=_safe_str(state_query_type) or query_type,
        conversation_id=conversation_id,
    )
    lines = ["تقصد أي تحليل بالضبط؟ هذه أقرب الخيارات:"]
    for idx, name in enumerate(candidates[:5], start=1):
        lines.append(f"{idx}) {name}")
    return "\n".join(lines)


def _build_ranked_disambiguation_reply(
    query_norm: str,
    *,
    query_type: str,
    state_query_type: str = "",
    records: list[dict[str, Any]],
    conversation_id: UUID | None = None,
) -> str | None:
    ranked = _rank_target_candidates(query_norm, records)
    if not ranked:
        return None

    candidates: list[str] = []
    seen: set[str] = set()
    for score, record in ranked:
        if score < 0.50:
            continue
        name = _safe_str(record.get("test_name_ar"))
        name_norm = _norm(name)
        if not name or name_norm in seen:
            continue
        seen.add(name_norm)
        candidates.append(name)
        if len(candidates) >= 4:
            break

    if len(candidates) < 2:
        return None

    set_tests_disambiguation_state(
        candidates,
        query_type=_safe_str(state_query_type) or query_type,
        conversation_id=conversation_id,
    )
    lines = ["تقصد أي تحليل بالضبط؟ هذه أقرب الخيارات:"]
    for idx, name in enumerate(candidates, start=1):
        lines.append(f"{idx}) {name}")
    return "\n".join(lines)


def resolve_tests_business_query(user_text: str, conversation_id: UUID | None = None) -> dict[str, Any]:
    """Resolve business-support test queries deterministically."""
    query = _safe_str(user_text)
    query_norm = _norm(query)
    if not query_norm:
        return {
            "matched": False,
            "answer": "",
            "route": "tests_business_no_match",
            "meta": {"query_type": "no_match", "reason": "empty_query"},
        }

    records = [r for r in load_tests_business_records() if bool(r.get("is_active", True))]
    if not records:
        records = load_tests_business_records()
    if not records:
        return {
            "matched": False,
            "answer": "",
            "route": "tests_business_no_match",
            "meta": {"query_type": "no_match", "reason": "dataset_unavailable"},
        }

    query_type = _detect_query_type(query_norm)
    preserved_primary_query_type, preserved_dual_intents = _load_preserved_dual_intents(conversation_id)
    preserved_dual_count = sum(1 for _, v in preserved_dual_intents.items() if v)
    if query_type == "no_match" and preserved_primary_query_type and _likely_selection_label_query(query_norm):
        query_type = preserved_primary_query_type
    if query_type == "no_match":
        return {
            "matched": False,
            "answer": "",
            "route": "tests_business_no_match",
            "meta": {"query_type": "no_match", "reason": "not_business_test_intent"},
        }

    if query_type == "test_symptoms_query":
        matches = _find_symptom_matches(query_norm, records)
        if not matches:
            return {
                "matched": True,
                "answer": _NOT_CLEAR_MESSAGE,
                "route": "tests_business_symptoms",
                "meta": {
                    "query_type": query_type,
                    "matched_count": 0,
                },
            }
        lines = ["التحاليل المناسبة بحسب الأعراض المذكورة (من البيانات الحالية):"]
        for idx, r in enumerate(matches, start=1):
            lines.append(f"{idx}) {_safe_str(r.get('test_name_ar'))}")
        return {
            "matched": True,
            "answer": "\n".join(lines),
            "route": "tests_business_symptoms",
            "meta": {
                "query_type": query_type,
                "matched_count": len(matches),
                "matched_test_id": _safe_str(matches[0].get("id")),
                "matched_test_name": _safe_str(matches[0].get("test_name_ar")),
            },
        }

    query_norm = _normalize_business_query_aliases(query_norm)
    supported_dual_intents = _detect_supported_dual_intents(query_norm)
    effective_dual_intents = preserved_dual_intents if preserved_dual_count >= 2 else supported_dual_intents
    target, score = _find_target_test(query_norm, records)
    if target is None and query_type in _RELAXED_BUSINESS_TARGET_TYPES:
        target_tokens = _extract_target_tokens_for_relevance(query_norm)
        if query_type == "test_sample_type_query" and not target_tokens:
            logger.debug(
                "tests_business relaxed_target_accept blocked | query=%s | query_type=%s | reason=generic_sample_type_without_target",
                query_norm,
                query_type,
            )
            ranked_candidates = []
        else:
            ranked_candidates = _rank_target_candidates(query_norm, records)
        if ranked_candidates:
            top_score, top_record = ranked_candidates[0]
            relevance = _record_relevance_score(top_record, target_tokens)
            if top_score >= _RELAXED_BUSINESS_TARGET_SCORE and relevance >= 0.34:
                logger.debug(
                    "tests_business relaxed_target_accept | query=%s | query_type=%s | top_score=%.3f | relevance=%.3f | threshold=%.3f | accepted=true",
                    query_norm,
                    query_type,
                    top_score,
                    relevance,
                    _RELAXED_BUSINESS_TARGET_SCORE,
                )
                target = top_record
                score = top_score
            else:
                logger.debug(
                    "tests_business relaxed_target_accept | query=%s | query_type=%s | top_score=%.3f | relevance=%.3f | threshold=%.3f | accepted=false",
                    query_norm,
                    query_type,
                    top_score,
                    relevance,
                    _RELAXED_BUSINESS_TARGET_SCORE,
                )
    if target is None:
        state_query_type = (
            _encode_dual_state_query_type(query_type, effective_dual_intents)
            if sum(1 for _, v in effective_dual_intents.items() if v) >= 2
            else query_type
        )
        ranked_disambiguation_reply = _build_ranked_disambiguation_reply(
            query_norm,
            query_type=query_type,
            state_query_type=state_query_type,
            records=records,
            conversation_id=conversation_id,
        )
        fallback_disambiguation_reply = _build_disambiguation_reply(
            query_norm or query,
            query_type=query_type,
            state_query_type=state_query_type,
            conversation_id=conversation_id,
        )
        disambiguation_reply = ranked_disambiguation_reply or fallback_disambiguation_reply
        return {
            "matched": True,
            "answer": disambiguation_reply or _TEST_NOT_FOUND_MESSAGE,
            "route": _TARGET_QUERY_ROUTE.get(query_type, "tests_business_no_match"),
            "meta": {
                "query_type": query_type,
                "matched_test_id": "",
                "matched_test_name": "",
                "score": 0.0,
                "disambiguation_used": bool(disambiguation_reply),
                "disambiguation_source": (
                    "ranked_candidates"
                    if bool(ranked_disambiguation_reply)
                    else ("rule_based" if bool(fallback_disambiguation_reply) else "")
                ),
            },
        }

    test_name = _safe_str(target.get("test_name_ar"))
    target_id = _safe_str(target.get("id"))

    # Deterministic same-domain dual-intent composition.
    if (
        sum(1 for _, v in effective_dual_intents.items() if v) >= 2
        and query_type in {"test_price_query", "test_fasting_query", "test_preparation_query", "test_sample_type_query"}
    ):
        answer = _format_dual_intent_composed_answer(
            query_norm,
            target,
            intents_override=effective_dual_intents,
        )
        return {
            "matched": True,
            "answer": answer,
            "route": _TARGET_QUERY_ROUTE.get(query_type, "tests_business_no_match"),
            "meta": {
                "query_type": query_type,
                "matched_test_id": target_id,
                "matched_test_name": test_name,
                "score": score,
            },
        }

    if query_type == "test_price_query":
        price_raw = _safe_str(target.get("price_raw"))
        answer = f"سعر تحليل {test_name} هو: {price_raw}." if price_raw else _FIELD_NOT_AVAILABLE_MESSAGE
        return {
            "matched": True,
            "answer": answer,
            "route": "tests_business_price",
            "meta": {
                "query_type": query_type,
                "matched_test_id": target_id,
                "matched_test_name": test_name,
                "score": score,
                "price_available": bool(price_raw),
            },
        }

    if query_type == "test_fasting_query":
        prep = _safe_str(target.get("preparation"))
        if prep and ("صيام" in prep or "الصيام" in prep):
            answer = f"بالنسبة لتحليل {test_name}، {prep}"
            available = True
        else:
            answer = (
                f"ما عندي تعليمات صيام مؤكدة لتحليل {test_name} في البيانات الحالية. "
                "اكتب اسم التحليل أو كوده بشكل أدق."
            )
            available = False
        return {
            "matched": True,
            "answer": answer,
            "route": "tests_business_fasting",
            "meta": {
                "query_type": query_type,
                "matched_test_id": target_id,
                "matched_test_name": test_name,
                "score": score,
                "fasting_available": available,
            },
        }

    if query_type == "test_preparation_query":
        prep = _safe_str(target.get("preparation"))
        if prep:
            answer = f"قبل تحليل {test_name}، {prep}"
        else:
            answer = (
                f"ما عندي تعليمات تحضير واضحة لتحليل {test_name} في البيانات الحالية. "
                "اكتب اسم التحليل أو كوده بشكل أدق."
            )
        return {
            "matched": True,
            "answer": answer,
            "route": "tests_business_preparation",
            "meta": {
                "query_type": query_type,
                "matched_test_id": target_id,
                "matched_test_name": test_name,
                "score": score,
                "preparation_available": bool(prep),
            },
        }

    if query_type == "test_complementary_query":
        values = _as_str_list(target.get("complementary_tests"))
        answer = (
            f"التحاليل المكملة لـ {test_name} قد تشمل:\n- " + "\n- ".join(values)
            if values
            else _NOT_CLEAR_MESSAGE
        )
        return {
            "matched": True,
            "answer": answer,
            "route": "tests_business_complementary",
            "meta": {
                "query_type": query_type,
                "matched_test_id": target_id,
                "matched_test_name": test_name,
                "score": score,
                "complementary_available": bool(values),
            },
        }

    if query_type == "test_alternative_query":
        values = _as_str_list(target.get("alternative_tests"))
        answer = (
            f"البدائل الممكنة لتحليل {test_name} قد تشمل:\n- " + "\n- ".join(values)
            if values
            else _NOT_CLEAR_MESSAGE
        )
        return {
            "matched": True,
            "answer": answer,
            "route": "tests_business_alternative",
            "meta": {
                "query_type": query_type,
                "matched_test_id": target_id,
                "matched_test_name": test_name,
                "score": score,
                "alternative_available": bool(values),
            },
        }

    if query_type == "test_sample_type_query":
        sample_type = _safe_str(target.get("sample_type"))
        if sample_type:
            answer = f"عينة تحليل {test_name} تكون عادة: {sample_type}"
        else:
            answer = (
                f"ما عندي نوع عينة موثق لتحليل {test_name} في البيانات الحالية. "
                "اكتب اسم التحليل أو كوده بشكل أدق."
            )
        return {
            "matched": True,
            "answer": answer,
            "route": "tests_business_sample_type",
            "meta": {
                "query_type": query_type,
                "matched_test_id": target_id,
                "matched_test_name": test_name,
                "score": score,
                "sample_type_available": bool(sample_type),
            },
        }

    return {
        "matched": False,
        "answer": "",
        "route": "tests_business_no_match",
        "meta": {"query_type": "no_match", "reason": "unhandled_query_type"},
    }


if __name__ == "__main__":
    samples = [
        "هل تحليل الحديد يحتاج صيام",
        "كم ساعة الصيام لتحليل السكر",
        "ما التحاليل المناسبة لتساقط الشعر",
        "ما التحاليل المكملة لفيتامين د",
        "ما البديل لتحليل كذا",
        "ما نوع عينة تحليل ANA",
    ]
    for text in samples:
        result = resolve_tests_business_query(text)
        print(f"INPUT: {text}")
        print(f"ROUTE: {result.get('route')}")
        print(f"MATCHED: {result.get('matched')}")
        print(f"META: {result.get('meta')}")
        print(f"ANSWER: {result.get('answer')}")
        print("-" * 72)
