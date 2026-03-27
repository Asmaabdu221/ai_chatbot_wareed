"""Deterministic runtime resolver for package queries."""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID

from app.services.runtime.selection_state import save_selection_state
from app.services.runtime.text_normalizer import normalize_arabic

PACKAGES_JSONL_PATH = Path("app/data/runtime/rag/packages_clean.jsonl")

_GENERAL_HINTS = (
    "باقات",
    "باقاتكم",
    "وش عندكم باقات",
    "ايش عندكم باقات",
    "عندكم باقات",
    "البرامج",
)
_PRICE_HINTS = ("كم سعر", "سعر", "بكم", "تكلفه", "تكلفة", "price")
_CATEGORY_HINTS: dict[str, tuple[str, ...]] = {
    "الباقات المتخصصة": ("رمضان", "متخصصة"),
    "الباقات الجينية التشخيصية": ("جيني", "وراثي", "تشخيصي"),
    "الباقات الجينية الوقائية": ("جيني", "وراثي", "وقائي"),
    "التحاليل المخبرية الفردية": ("تحاليل فردية", "فردية", "مخبرية"),
    "التحاليل الذاتية": ("ذاتي", "التحاليل الذاتية"),
    "التحاليل الجينية": ("تحاليل جينية", "genetic"),
}

_PRICE_NOT_AVAILABLE = "سعر هذه الباقة غير متوفر حاليًا في البيانات الحالية."
_PACKAGE_NOT_FOUND = "ما قدرت أحدد باقة محددة من سؤالك. اكتب اسم الباقة بشكل أوضح."


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _norm(value: Any) -> str:
    return normalize_arabic(_safe_str(value))


def _to_float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = _safe_str(value)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


@lru_cache(maxsize=1)
def load_packages_records() -> list[dict[str, Any]]:
    """Load runtime package records from JSONL with helper normalized fields."""
    if not PACKAGES_JSONL_PATH.exists():
        return []

    rows: list[dict[str, Any]] = []
    with PACKAGES_JSONL_PATH.open("r", encoding="utf-8") as f:
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
            main_category = _safe_str(obj.get("main_category"))
            offering_type = _safe_str(obj.get("offering_type"))
            if not package_name or not main_category or not offering_type:
                continue

            item = dict(obj)
            item["id"] = _safe_str(obj.get("id"))
            item["source"] = _safe_str(obj.get("source")) or "packages"
            item["main_category"] = main_category
            item["offering_type"] = offering_type
            item["package_name"] = package_name
            item["description_short"] = _safe_str(obj.get("description_short"))
            item["description_full"] = _safe_str(obj.get("description_full"))
            item["price_raw"] = _safe_str(obj.get("price_raw"))
            item["price_number"] = _to_float_or_none(obj.get("price_number"))
            item["currency"] = _safe_str(obj.get("currency"))
            item["included_count"] = obj.get("included_count")
            item["runtime_present"] = bool(obj.get("runtime_present"))
            item["review_issues"] = _safe_str(obj.get("review_issues"))
            item["source_row"] = obj.get("source_row")
            item["is_active"] = bool(obj.get("is_active", True))
            item["package_name_norm"] = _norm(package_name)
            item["main_category_norm"] = _norm(main_category)
            rows.append(item)
    return rows


def _is_price_query(query_norm: str) -> bool:
    return any(_norm(h) in query_norm for h in _PRICE_HINTS)


def _is_general_query(query_norm: str) -> bool:
    return any(_norm(h) in query_norm for h in _GENERAL_HINTS)


def _detect_category(query_norm: str, records: list[dict[str, Any]]) -> str:
    categories = {
        _safe_str(r.get("main_category")): _safe_str(r.get("main_category_norm")) for r in records
    }
    for cat, cat_norm in categories.items():
        if cat_norm and cat_norm in query_norm:
            return cat

    for category, hints in _CATEGORY_HINTS.items():
        if any(_norm(h) in query_norm for h in hints):
            return category
    return ""


def _is_category_like_query(query_norm: str, detected_category: str) -> bool:
    if not query_norm:
        return False

    category_tokens = (
        "التحاليل الذاتية",
        "التحاليل الجينية",
        "الباقات الجينية",
        "فئة",
        "تصنيف",
    )
    if any(_norm(t) in query_norm for t in category_tokens):
        return True
    return False


def _score_package_match(query_norm: str, record: dict[str, Any]) -> float:
    name_norm = _safe_str(record.get("package_name_norm"))
    if not name_norm:
        return 0.0
    if query_norm == name_norm:
        return 1.0
    if name_norm in query_norm or query_norm in name_norm:
        return 0.9
    return SequenceMatcher(None, query_norm, name_norm).ratio()


def _find_specific_package(query_norm: str, records: list[dict[str, Any]]) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_score = 0.0
    for record in records:
        score = _score_package_match(query_norm, record)
        if score > best_score:
            best_score = score
            best = record
    if best is None:
        return None
    if best_score < 0.72:
        return None
    return best


def _format_general_overview(records: list[dict[str, Any]]) -> str:
    counts: dict[str, int] = {}
    for r in records:
        cat = _safe_str(r.get("main_category"))
        if cat:
            counts[cat] = counts.get(cat, 0) + 1

    lines = ["هذه أبرز فئات الباقات المتاحة حاليًا:"]
    for cat in sorted(counts):
        lines.append(f"- {cat} ({counts[cat]})")
    lines.append("اكتب اسم الفئة أو اسم الباقة مباشرة عشان أعرض التفاصيل.")
    return "\n".join(lines)


def _format_category_packages(category: str, records: list[dict[str, Any]]) -> str:
    rows = [r for r in records if _safe_str(r.get("main_category")) == category]
    if not rows:
        return "ما لقيت باقات في هذه الفئة حاليًا."

    lines = [f"الباقات المتاحة ضمن فئة {category}:"]
    for idx, r in enumerate(rows[:15], start=1):
        name = _safe_str(r.get("package_name"))
        price = r.get("price_number")
        if isinstance(price, (int, float)):
            lines.append(f"{idx}) {name} - {price:g} {_safe_str(r.get('currency') or 'ريال')}")
        else:
            lines.append(f"{idx}) {name}")
    if len(rows) > 15:
        lines.append(f"... ({len(rows) - 15} باقات إضافية)")
    return "\n".join(lines)


def _format_package_details(record: dict[str, Any]) -> str:
    name = _safe_str(record.get("package_name"))
    category = _safe_str(record.get("main_category"))
    offering_type = _safe_str(record.get("offering_type"))
    desc = _safe_str(record.get("description_short")) or _safe_str(record.get("description_full"))
    currency = _safe_str(record.get("currency") or "ريال")
    price = record.get("price_number")

    lines = [
        f"{name}",
        f"الفئة: {category}",
        f"النوع: {offering_type}",
    ]
    if desc:
        lines.append(f"الوصف: {desc}")
    if isinstance(price, (int, float)):
        lines.append(f"السعر: {price:g} {currency}")
    else:
        lines.append(_PRICE_NOT_AVAILABLE)
    return "\n".join(lines)


def _format_package_price(record: dict[str, Any]) -> str:
    name = _safe_str(record.get("package_name"))
    currency = _safe_str(record.get("currency") or "ريال")
    price = record.get("price_number")
    if isinstance(price, (int, float)):
        return f"سعر {name}: {price:g} {currency}."
    return _PRICE_NOT_AVAILABLE


def resolve_packages_query(user_text: str, conversation_id: UUID | None = None) -> dict[str, Any]:
    """Resolve package queries deterministically from runtime package dataset."""
    query = _safe_str(user_text)
    query_norm = _norm(query)
    if not query_norm:
        return {
            "matched": False,
            "answer": "",
            "route": "packages_no_match",
            "meta": {"query_type": "no_match", "reason": "empty_query"},
        }

    records = [r for r in load_packages_records() if bool(r.get("is_active", True))]
    if not records:
        records = load_packages_records()
    if not records:
        return {
            "matched": False,
            "answer": "",
            "route": "packages_no_match",
            "meta": {"query_type": "no_match", "reason": "packages_data_unavailable"},
        }

    category = _detect_category(query_norm, records)
    category_like = _is_category_like_query(query_norm, category)
    general_like = _is_general_query(query_norm)
    price_query = _is_price_query(query_norm)
    specific_match = _find_specific_package(query_norm, records)

    # Category queries should win over specific matching when the query is
    # clearly about a category label, not a package name.
    if category and category_like and not price_query and specific_match is None:
        category_rows = [r for r in records if _safe_str(r.get("main_category")) == category]
        if conversation_id is not None and category_rows:
            save_selection_state(
                conversation_id,
                options=[
                    {
                        "id": _safe_str(row.get("id")) or f"package_option::{idx}",
                        "label": _safe_str(row.get("package_name")),
                        "selection_payload": {
                            "package_name": _safe_str(row.get("package_name")),
                        },
                    }
                    for idx, row in enumerate(category_rows[:15], start=1)
                ],
                selection_type="package",
                query_type="package_category",
            )
        return {
            "matched": True,
            "answer": _format_category_packages(category, records),
            "route": "packages_category",
            "meta": {
                "query_type": "package_category",
                "category": category,
            },
        }

    if price_query and specific_match is not None:
        package_id = _safe_str(specific_match.get("id"))
        return {
            "matched": True,
            "answer": _format_package_price(specific_match),
            "route": "packages_price",
            "meta": {
                "query_type": "package_price_query",
                "matched_package_id": package_id,
                "category": _safe_str(specific_match.get("main_category")),
                "price_available": isinstance(specific_match.get("price_number"), (int, float)),
            },
        }

    if specific_match is not None:
        package_id = _safe_str(specific_match.get("id"))
        return {
            "matched": True,
            "answer": _format_package_details(specific_match),
            "route": "packages_specific",
            "meta": {
                "query_type": "package_specific",
                "matched_package_id": package_id,
                "category": _safe_str(specific_match.get("main_category")),
            },
        }

    if category:
        return {
            "matched": True,
            "answer": _format_category_packages(category, records),
            "route": "packages_category",
            "meta": {
                "query_type": "package_category",
                "category": category,
            },
        }

    if general_like or "باقه" in query_norm or "باقات" in query_norm:
        return {
            "matched": True,
            "answer": _format_general_overview(records),
            "route": "packages_general",
            "meta": {
                "query_type": "package_general",
                "categories_count": len({_safe_str(r.get('main_category')) for r in records}),
            },
        }

    if price_query:
        return {
            "matched": True,
            "answer": _PACKAGE_NOT_FOUND,
            "route": "packages_price",
            "meta": {
                "query_type": "package_price_query",
                "matched_package_id": "",
                "reason": "price_query_without_specific_package",
            },
        }

    return {
        "matched": False,
        "answer": "",
        "route": "packages_no_match",
        "meta": {"query_type": "no_match", "reason": "not_packages_intent"},
    }


if __name__ == "__main__":
    try:
        import sys

        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    samples = [
        "وش عندكم باقات",
        "باقات رمضان",
        "باقة نهار رمضان الشاملة",
        "كم سعر باقة نهار رمضان الشاملة",
    ]
    for text in samples:
        result = resolve_packages_query(text)
        print(f"INPUT: {text}")
        print(f"ROUTE: {result.get('route')}")
        print(f"MATCHED: {result.get('matched')}")
        print(f"META: {result.get('meta')}")
        print(f"ANSWER: {result.get('answer')}")
        print("-" * 72)
