"""Deterministic loader for enriched packages business dataset."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID

from app.services.runtime.selection_state import save_selection_state
from app.services.runtime.text_normalizer import normalize_arabic

PACKAGES_BUSINESS_JSONL_PATH = Path("app/data/runtime/rag/packages_business_clean.jsonl")
TESTS_BUSINESS_JSONL_PATH = Path("app/data/runtime/rag/tests_business_clean.jsonl")
PRIMARY_PACKAGES_DATASET_PATH = PACKAGES_BUSINESS_JSONL_PATH

_PRICE_HINTS = (
    "كم سعر",
    "سعر",
    "بكم",
    "تكلفه",
    "تكلفة",
    "price",
)
_CHEAPEST_HINTS = (
    "ارخص",
    "الأرخص",
    "اقل سعر",
    "أقل سعر",
    "الاقل",
    "أقل",
    "cheapest",
)
_BEST_FOR_CONDITION_HINTS = (
    "ل",
    "مناسب",
    "افضل",
    "أفضل",
    "for",
)
_CATEGORY_HINTS = (
    "باقات",
    "فئة",
    "تصنيف",
    "فئات",
    "category",
)


_SPECIFIC_PACKAGE_HINTS = (
    "ابغى باقة",
    "ابغي باقة",
    "ابي باقة",
    "أبي باقة",
    "عندكم باقة",
    "وش تشمل باقة",
    "ايش تشمل باقة",
    "ايش فيها باقة",
    "وش فيها باقة",
)


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _norm(value: Any) -> str:
    return normalize_arabic(_safe_str(value))


def _as_list_of_str(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_safe_str(v) for v in value if _safe_str(v)]
    text = _safe_str(value)
    return [text] if text else []


def _has_any_hint(query_norm: str, hints: tuple[str, ...]) -> bool:
    return any(_norm(h) in query_norm for h in hints)


@lru_cache(maxsize=1)
def _load_tests_business_match_index() -> list[dict[str, Any]]:
    """Load minimal bilingual test matching index from tests_business dataset."""
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

            test_name_ar = _safe_str(obj.get("test_name_ar"))
            english_name = _safe_str(obj.get("english_name"))
            code_alt_name = _safe_str(obj.get("code_alt_name"))
            matched_name = _safe_str(obj.get("matched_name"))

            match_terms_norm = _as_list_of_str(obj.get("match_terms_norm"))
            if not match_terms_norm:
                fallback_terms = [
                    test_name_ar,
                    english_name,
                    code_alt_name,
                    matched_name,
                    *_as_list_of_str(obj.get("alias_terms")),
                    *_as_list_of_str(obj.get("match_terms")),
                ]
                match_terms_norm = [_norm(v) for v in fallback_terms if _norm(v)]
            else:
                match_terms_norm = [_norm(v) for v in match_terms_norm if _norm(v)]

            if not match_terms_norm:
                continue

            rows.append(
                {
                    "test_name_ar": test_name_ar,
                    "english_name": english_name,
                    "terms_norm": list(dict.fromkeys(match_terms_norm)),
                }
            )
    return rows


def _expand_test_terms_from_source(test_text: str) -> list[str]:
    """Expand one package test term using existing bilingual tests source terms."""
    seed = _norm(test_text)
    if not seed:
        return []

    expanded: list[str] = [seed]
    seen: set[str] = {seed}

    for rec in _load_tests_business_match_index():
        terms = list(rec.get("terms_norm") or [])
        if not terms:
            continue
        if not any(seed == t or seed in t or t in seed for t in terms):
            continue
        for term in terms:
            if term and term not in seen:
                seen.add(term)
                expanded.append(term)
    return expanded


def detect_packages_query_type(query: str) -> str:
    """Detect deterministic packages query type from user query text."""
    query_norm = _norm(query)
    if not query_norm:
        return "category_query"

    if _has_any_hint(query_norm, _CHEAPEST_HINTS):
        return "cheapest_query"

    if _has_any_hint(query_norm, _PRICE_HINTS):
        return "price_query"

    if _has_any_hint(query_norm, _SPECIFIC_PACKAGE_HINTS):
        return "specific_package_query"

    # Condition-style asks: "افضل باقة لتساقط الشعر", "باقة مناسبة للتعب".
    condition_markers = (
        "لت",
        "لل",
        "لـ",
        "مناسب",
        "افضل",
        "أفضل",
        "تساقط",
        "فقر دم",
        "نقص",
        "دوخه",
        "دوخة",
        "تعب",
    )
    if any(marker in query_norm for marker in condition_markers):
        return "best_for_condition_query"

    if "باقه" in query_norm or "باقة" in query_norm:
        if _has_any_hint(query_norm, _CATEGORY_HINTS):
            return "category_query"
        return "specific_package_query"

    if _has_any_hint(query_norm, _CATEGORY_HINTS):
        return "category_query"

    # Fallback for package-oriented requests without clear entity.
    return "category_query"


def extract_package_target(query: str) -> str:
    """Extract likely package target phrase from user query."""
    query_norm = _norm(query)
    if not query_norm:
        return ""

    stopwords = {
        "باقه",
        "باقة",
        "باقات",
        "سعر",
        "كم",
        "افضل",
        "أفضل",
        "ارخص",
        "الأرخص",
        "مناسب",
        "مناسبة",
        "وش",
        "ايش",
        "ابي",
        "أبي",
        "عندكم",
        "ل",
        "باقاتكم",
        "ابغى",
        "ابغي",
        "تشمل",
        "يشمل",
        "فيها",
        "داخلها",
        "داخل",
        "محتواها",
        "محتوى",
        "مكوناتها",
    }

    tokens = [t for t in query_norm.split() if t]
    cleaned: list[str] = []
    for token in tokens:
        t = token.strip("-_")
        if not t:
            continue
        # Strip common attached prepositions conservatively.
        if (t.startswith("لل") or t.startswith("ل")) and len(t) > 3:
            t = t[2:] if t.startswith("لل") else t[1:]
        if t in stopwords:
            continue
        cleaned.append(t)

    return " ".join(cleaned[:6]).strip()


def match_packages_deterministic(query: str, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Match packages deterministically using package_name, aliases, and themes."""
    query_norm = _norm(query)
    target_norm = _norm(extract_package_target(query))
    search_terms = [v for v in (query_norm, target_norm) if v]
    if not search_terms or not records:
        return []

    exact_matches: list[dict[str, Any]] = []
    substring_matches: list[dict[str, Any]] = []
    seen_names: set[str] = set()

    for record in records:
        name_norm = _safe_str(record.get("package_name_norm"))
        aliases_norm = list(record.get("aliases_norm") or [])
        themes_norm = list(record.get("themes_norm") or [])
        tests = list(record.get("tests_included") or [])
        tests_norm: list[str] = []
        for test_value in tests:
            tests_norm.extend(_expand_test_terms_from_source(_safe_str(test_value)))
        tests_norm = list(dict.fromkeys([t for t in tests_norm if t]))
        fields = [name_norm] + aliases_norm + themes_norm + tests_norm
        fields = [f for f in fields if f]
        if not fields:
            continue

        is_exact = any(term == field for term in search_terms for field in fields)
        is_substring = any(term in field or field in term for term in search_terms for field in fields)
        record_key = name_norm or _safe_str(record.get("package_name"))
        if not record_key or record_key in seen_names:
            continue

        if is_exact:
            exact_matches.append(record)
            seen_names.add(record_key)
            continue
        if is_substring:
            substring_matches.append(record)
            seen_names.add(record_key)

    return exact_matches + substring_matches


@lru_cache(maxsize=1)
def load_packages_business_records() -> list[dict[str, Any]]:
    """Load curated business packages only from packages_business_clean.jsonl."""
    if not PRIMARY_PACKAGES_DATASET_PATH.exists():
        return []

    rows: list[dict[str, Any]] = []
    with PRIMARY_PACKAGES_DATASET_PATH.open("r", encoding="utf-8") as f:
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

            package_name = _safe_str(obj.get("package_name"))
            aliases = _as_list_of_str(obj.get("aliases"))
            themes = _as_list_of_str(obj.get("themes"))
            best_for = _as_list_of_str(obj.get("best_for"))

            if not package_name:
                continue

            item = dict(obj)
            item["package_name"] = package_name
            item["aliases"] = aliases
            item["themes"] = themes
            item["best_for"] = best_for
            item["main_category"] = _safe_str(obj.get("main_category"))
            item["price"] = _safe_str(obj.get("price"))
            item["price_text"] = _safe_str(obj.get("price_text"))
            item["tests_included"] = _as_list_of_str(obj.get("tests_included"))
            item["summary"] = _safe_str(obj.get("summary"))

            item["package_name_norm"] = _norm(package_name)
            item["aliases_norm"] = [_norm(v) for v in aliases if _norm(v)]
            item["themes_norm"] = [_norm(v) for v in themes if _norm(v)]
            item["best_for_norm"] = [_norm(v) for v in best_for if _norm(v)]

            rows.append(item)
    return rows


def load_primary_packages_records() -> list[dict[str, Any]]:
    """Primary user-facing package matching dataset (curated business list only)."""
    return load_packages_business_records()


def format_packages_response(
    response_type: str,
    *,
    package: dict[str, Any] | None = None,
    packages: list[dict[str, Any]] | None = None,
) -> str:
    """Format short, clear, structured Arabic package responses."""
    kind = _safe_str(response_type)
    row = dict(package or {})
    rows = list(packages or [])

    if kind == "price":
        name = _safe_str(row.get("package_name"))
        price_text = _safe_str(row.get("price_text")) or (_safe_str(row.get("price")) + " ريال" if _safe_str(row.get("price")) else "")
        if not name:
            return "ما قدرت أحدد اسم الباقة."
        if not price_text:
            return f"سعر باقة {name} غير متوفر حالياً."
        return f"سعر باقة {name}: {price_text}."

    if kind == "cheapest":
        name = _safe_str(row.get("package_name"))
        price_text = _safe_str(row.get("price_text")) or (_safe_str(row.get("price")) + " ريال" if _safe_str(row.get("price")) else "")
        if not name:
            return "حالياً ما قدرت أحدد أرخص باقة."
        lines = ["أرخص باقة حالياً:", f"- {name}"]
        if price_text:
            lines.append(f"- السعر: {price_text}")
        return "\n".join(lines)

    if kind == "best_for":
        if not rows:
            return "ما لقيت باقات مناسبة حسب طلبك."
        lines = ["الباقات المناسبة:"]
        for idx, item in enumerate(rows[:5], start=1):
            name = _safe_str(item.get("package_name"))
            price_text = _safe_str(item.get("price_text"))
            lines.append(f"{idx}) {name}" + (f" - {price_text}" if price_text else ""))
        return "\n".join(lines)

    if kind == "specific":
        name = _safe_str(row.get("package_name"))
        category = _safe_str(row.get("main_category"))
        price_text = _safe_str(row.get("price_text")) or (_safe_str(row.get("price")) + " ريال" if _safe_str(row.get("price")) else "غير متوفر")
        summary = _safe_str(row.get("summary"))
        tests = [_safe_str(t) for t in list(row.get("tests_included") or []) if _safe_str(t)]
        lines = [name or "الباقة", f"الفئة: {category or 'غير متوفر'}", f"السعر: {price_text}"]
        if summary:
            lines.append(f"الملخص: {summary}")
        if tests:
            lines.append("أبرز التحاليل: " + "، ".join(tests[:5]))
        return "\n".join(lines)

    return "لا توجد نتيجة مناسبة حالياً."


def _package_guidance_text(package: dict[str, Any]) -> str:
    """Build short guidance from best_for (max 3 items)."""
    best_for = [_safe_str(v) for v in list(package.get("best_for") or []) if _safe_str(v)]
    if not best_for:
        return ""
    lines = ["", "تفيد هذه الباقة في:"]
    for item in best_for[:3]:
        lines.append(f"- {item}")
    return "\n".join(lines)


def handle_packages_business_query(query: str, conversation_id: UUID | None = None) -> dict[str, Any]:
    """Resolve enriched package queries with deterministic business logic."""
    query_text = _safe_str(query)
    query_type = detect_packages_query_type(query_text)
    records = load_primary_packages_records()

    if not query_text:
        return {
            "matched": False,
            "query_type": query_type,
            "answer": "",
            "results": [],
            "reason": "empty_query",
        }

    if not records:
        return {
            "matched": False,
            "query_type": query_type,
            "answer": "",
            "results": [],
            "reason": "packages_business_data_unavailable",
        }

    matches = match_packages_deterministic(query_text, records)

    if query_type == "price_query":
        if not matches:
            return {
                "matched": False,
                "query_type": query_type,
                "answer": "ما قدرت أحدد باقة محددة من سؤالك. اكتب اسم الباقة بشكل أوضح.",
                "results": [],
            }
        package = matches[0]
        price_text = _safe_str(package.get("price_text"))
        if not price_text:
            price_value = _safe_str(package.get("price"))
            price_text = f"{price_value} ريال" if price_value else ""
        answer = f"سعر {_safe_str(package.get('package_name'))}: {price_text}." if price_text else "سعر هذه الباقة غير متوفر حالياً."
        return {
            "matched": True,
            "query_type": query_type,
            "answer": answer,
            "results": [package],
        }

    if query_type == "cheapest_query":
        priced_rows: list[tuple[float, dict[str, Any]]] = []
        for row in (matches or records):
            price_value = _safe_str(row.get("price"))
            if not price_value:
                continue
            try:
                priced_rows.append((float(price_value), row))
            except ValueError:
                continue
        if not priced_rows:
            return {
                "matched": False,
                "query_type": query_type,
                "answer": "حالياً ما عندي سعر واضح لاختيار أرخص باقة.",
                "results": [],
            }
        priced_rows.sort(key=lambda x: x[0])
        cheapest = priced_rows[0][1]
        price_text = _safe_str(cheapest.get("price_text")) or f"{priced_rows[0][0]:g} ريال"
        guidance = _package_guidance_text(cheapest)
        return {
            "matched": True,
            "query_type": query_type,
            "answer": f"أرخص باقة حالياً: {_safe_str(cheapest.get('package_name'))} بسعر {price_text}.{guidance}",
            "results": [cheapest],
        }

    if query_type == "best_for_condition_query":
        if not matches:
            return {
                "matched": False,
                "query_type": query_type,
                "answer": "ما لقيت باقات مطابقة للحالة المذكورة بشكل واضح.",
                "results": [],
            }
        lines = ["الباقات المناسبة حسب طلبك:"]
        for idx, row in enumerate(matches[:10], start=1):
            price_text = _safe_str(row.get("price_text"))
            if price_text:
                lines.append(f"{idx}) {_safe_str(row.get('package_name'))} - {price_text}")
            else:
                lines.append(f"{idx}) {_safe_str(row.get('package_name'))}")
        if conversation_id is not None:
            save_selection_state(
                conversation_id,
                options=[
                    {
                        "id": f"package_option::{idx}",
                        "label": _safe_str(row.get("package_name")),
                        "selection_payload": {
                            "package_name": _safe_str(row.get("package_name")),
                        },
                    }
                    for idx, row in enumerate(matches[:10], start=1)
                ],
                selection_type="package",
                query_type=query_type,
            )
        guidance = _package_guidance_text(matches[0])
        return {
            "matched": True,
            "query_type": query_type,
            "answer": "\n".join(lines) + guidance,
            "results": matches[:10],
        }

    if query_type == "specific_package_query":
        if not matches:
            return {
                "matched": False,
                "query_type": query_type,
                "answer": "ما قدرت أحدد باقة محددة من سؤالك. اكتب اسم الباقة بشكل أوضح.",
                "results": [],
            }
        package = matches[0]
        tests = [t for t in list(package.get("tests_included") or []) if _safe_str(t)]
        tests_text = ", ".join(tests[:8]) if tests else "غير متوفر"
        answer_lines = [
            _safe_str(package.get("package_name")),
            f"الفئة: {_safe_str(package.get('main_category'))}",
            f"السعر: {_safe_str(package.get('price_text')) or _safe_str(package.get('price')) or 'غير متوفر'}",
            f"الملخص: {_safe_str(package.get('summary')) or 'غير متوفر'}",
            f"أبرز التحاليل: {tests_text}",
        ]
        guidance = _package_guidance_text(package)
        return {
            "matched": True,
            "query_type": query_type,
            "answer": "\n".join(answer_lines) + guidance,
            "results": [package],
        }

    # category_query fallback
    rows = matches if matches else records
    if conversation_id is not None and rows:
        save_selection_state(
            conversation_id,
            options=[
                {
                    "id": f"package_option::{idx}",
                    "label": _safe_str(row.get("package_name")),
                    "selection_payload": {
                        "package_name": _safe_str(row.get("package_name")),
                    },
                }
                for idx, row in enumerate(rows[:12], start=1)
            ],
            selection_type="package",
            query_type=query_type,
        )
    lines = ["الباقات المتاحة حالياً:"]
    for idx, row in enumerate(rows[:12], start=1):
        price_text = _safe_str(row.get("price_text"))
        lines.append(f"{idx}) {_safe_str(row.get('package_name'))}" + (f" - {price_text}" if price_text else ""))
    return {
        "matched": True,
        "query_type": query_type,
        "answer": "\n".join(lines),
        "results": rows[:12],
    }
