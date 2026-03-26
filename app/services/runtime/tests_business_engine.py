"""Deterministic business engine for test support queries."""

from __future__ import annotations

import json
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.services.runtime.text_normalizer import normalize_arabic

TESTS_BUSINESS_JSONL_PATH = Path("app/data/runtime/rag/tests_business_clean.jsonl")

_FASTING_HINTS = ("صيام", "صايم", "كم ساعه الصيام", "كم ساعة الصيام", "fasting")
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
_SAMPLE_TYPE_HINTS = ("نوع عينه", "نوع العينه", "العينه", "العينة", "sample type")

_NOT_CLEAR_MESSAGE = "المعلومة غير واضحة بشكل كافٍ في البيانات الحالية."
_TEST_NOT_FOUND_MESSAGE = "ما قدرت أحدد التحليل المقصود بدقة. اكتب اسم التحليل بشكل أوضح."
_TARGET_QUERY_ROUTE = {
    "test_fasting_query": "tests_business_fasting",
    "test_preparation_query": "tests_business_preparation",
    "test_complementary_query": "tests_business_complementary",
    "test_alternative_query": "tests_business_alternative",
    "test_sample_type_query": "tests_business_sample_type",
}


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
    return any(_norm(h) in query_norm for h in hints)


def _detect_query_type(query_norm: str) -> str:
    if _has_any_hint(query_norm, _COMPLEMENTARY_HINTS):
        return "test_complementary_query"
    if _has_any_hint(query_norm, _ALTERNATIVE_HINTS):
        return "test_alternative_query"
    if _has_any_hint(query_norm, _SAMPLE_TYPE_HINTS):
        return "test_sample_type_query"
    if _has_any_hint(query_norm, _FASTING_HINTS):
        return "test_fasting_query"
    if _has_any_hint(query_norm, _PREPARATION_HINTS):
        return "test_preparation_query"
    if _has_any_hint(query_norm, _SYMPTOMS_HINTS):
        return "test_symptoms_query"
    return "no_match"


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


def _find_target_test(query_norm: str, records: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, float]:
    candidate = _extract_test_candidate(query_norm)
    primary = candidate or query_norm

    best: dict[str, Any] | None = None
    best_score = 0.0
    for r in records:
        score = _score_record_match(primary, r)
        # Secondary weak signal from full query.
        score = max(score, _score_record_match(query_norm, r) * 0.7)
        if score > best_score:
            best = r
            best_score = score
    if best is None or best_score < 0.62:
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
    text = query_norm
    for marker in ("تحليل", "فحص", "اختبار"):
        if marker in text:
            tail = text.split(marker, 1)[1].strip()
            if tail:
                return _clean_candidate_phrase(tail)
    return _clean_candidate_phrase(text)


def _clean_candidate_phrase(text: str) -> str:
    tokens = _tokenize(text)
    if not tokens:
        return ""
    drop = {
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
    if code_like:
        return " ".join(code_like[:3]).strip()
    return " ".join(out[:5]).strip()


def _format_target_field(title: str, test_name: str, value: str) -> str:
    return f"{title} {test_name}:\n{value}"


def resolve_tests_business_query(user_text: str) -> dict[str, Any]:
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

    target, score = _find_target_test(query_norm, records)
    if target is None:
        return {
            "matched": True,
            "answer": _TEST_NOT_FOUND_MESSAGE,
            "route": _TARGET_QUERY_ROUTE.get(query_type, "tests_business_no_match"),
            "meta": {
                "query_type": query_type,
                "matched_test_id": "",
                "matched_test_name": "",
                "score": 0.0,
            },
        }

    test_name = _safe_str(target.get("test_name_ar"))
    target_id = _safe_str(target.get("id"))

    if query_type == "test_fasting_query":
        prep = _safe_str(target.get("preparation"))
        if prep and ("صيام" in prep or "الصيام" in prep):
            answer = _format_target_field("تعليمات الصيام لـ", test_name, prep)
            available = True
        else:
            answer = _NOT_CLEAR_MESSAGE
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
        answer = _format_target_field("تعليمات التحضير لـ", test_name, prep) if prep else _NOT_CLEAR_MESSAGE
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
            f"التحاليل المكملة لـ {test_name}:\n- " + "\n- ".join(values)
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
            f"البدائل المتاحة لـ {test_name}:\n- " + "\n- ".join(values)
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
        answer = _format_target_field("نوع العينة لـ", test_name, sample_type) if sample_type else _NOT_CLEAR_MESSAGE
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
