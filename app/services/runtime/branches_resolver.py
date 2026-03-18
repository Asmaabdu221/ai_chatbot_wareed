"""Deterministic runtime resolver for branches data."""

from __future__ import annotations

import json
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.services.runtime.text_normalizer import normalize_arabic

_BRANCHES_PATH = Path("app/data/runtime/rag/branches_clean.jsonl")

_GENERIC_BRANCHES_HINTS = (
    "فروعكم",
    "فروع",
    "اين تتواجد",
    "وين فروع",
)
_SPECIFIC_BRANCH_HINTS = (
    "اقرب",
    "الاقرب",
    "فرع",
    "فرع في",
    "بال",
    "في ",
)
_CITY_STOPWORDS = {
    "منطقه",
    "منطقة",
    "فروع",
    "فرع",
    "مختبر",
    "مختبرات",
    "وريد",
}


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _extract_city_from_section(section: str) -> str:
    section_norm = normalize_arabic(section)
    if not section_norm:
        return ""
    tokens = [t for t in section_norm.split() if t and t not in _CITY_STOPWORDS]
    if not tokens:
        return ""
    if len(tokens) >= 2 and tokens[0] == "مكه" and tokens[1] == "المكرمه":
        return "مكه المكرمه"
    return tokens[-1]


@lru_cache(maxsize=1)
def load_branches_records() -> list[dict[str, Any]]:
    """Load branches JSONL records with normalized helper fields."""
    if not _BRANCHES_PATH.exists():
        return []

    records: list[dict[str, Any]] = []
    with _BRANCHES_PATH.open("r", encoding="utf-8") as f:
        for raw_line in f:
            line = _safe_str(raw_line)
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            branch_name = _safe_str(row.get("branch_name"))
            section = _safe_str(row.get("section"))
            if not branch_name and not section:
                continue
            city = _extract_city_from_section(section)
            item = dict(row)
            item["branch_name"] = branch_name
            item["section"] = section
            item["city"] = city
            item["branch_norm"] = normalize_arabic(branch_name)
            item["section_norm"] = normalize_arabic(section)
            item["city_norm"] = normalize_arabic(city)
            item["raw_norm"] = normalize_arabic(_safe_str(row.get("raw_text")))
            records.append(item)
    return records


def _is_generic_branches_query(query_norm: str) -> bool:
    if not query_norm:
        return False
    return any(normalize_arabic(h) in query_norm for h in _GENERIC_BRANCHES_HINTS)


def _is_specific_branches_query(query_norm: str) -> bool:
    if not query_norm:
        return False
    return any(normalize_arabic(h) in query_norm for h in _SPECIFIC_BRANCH_HINTS)


def _detect_city(query_norm: str, records: list[dict[str, Any]]) -> str:
    cities = sorted({_safe_str(r.get("city_norm")) for r in records if _safe_str(r.get("city_norm"))}, key=len, reverse=True)
    for city in cities:
        if city and city in query_norm:
            return city
    return ""


def _format_branch_line(record: dict[str, Any]) -> str:
    name = _safe_str(record.get("branch_name"))
    city = _safe_str(record.get("city"))
    hours = _safe_str(record.get("hours"))
    map_url = _safe_str(record.get("map_url"))
    parts = [name]
    if city:
        parts.append(f"({city})")
    if hours:
        parts.append(f"- {hours}")
    if map_url:
        parts.append(f"- {map_url}")
    return " ".join(parts).strip()


def _match_specific_branch(query_norm: str, records: list[dict[str, Any]]) -> dict[str, Any] | None:
    # Deterministic contains checks first.
    for r in records:
        b = _safe_str(r.get("branch_norm"))
        if b and (b in query_norm or query_norm in b):
            return r
    for r in records:
        raw = _safe_str(r.get("raw_norm"))
        if raw and (raw in query_norm or query_norm in raw):
            return r

    # Semantic fallback only when deterministic checks fail.
    best: dict[str, Any] | None = None
    best_score = 0.0
    for r in records:
        for text in (_safe_str(r.get("branch_norm")), _safe_str(r.get("raw_norm"))):
            if not text:
                continue
            score = SequenceMatcher(None, query_norm, text).ratio()
            if score > best_score:
                best_score = score
                best = r
    if best and best_score >= 0.72:
        return best
    return None


def resolve_branches_query(user_text: str) -> dict[str, Any]:
    """Resolve branches query from branches_clean.jsonl only."""
    query = _safe_str(user_text)
    query_norm = normalize_arabic(query)
    if not query_norm:
        return {"matched": False, "answer": "", "meta": {"reason": "empty_query"}, "route": "branches_no_match"}

    records = load_branches_records()
    if not records:
        return {"matched": False, "answer": "", "meta": {"reason": "branches_data_unavailable"}, "route": "branches_no_match"}

    city_norm = _detect_city(query_norm, records)
    city_records = [r for r in records if city_norm and _safe_str(r.get("city_norm")) == city_norm]

    specific = _is_specific_branches_query(query_norm)
    generic = _is_generic_branches_query(query_norm)

    # Branch name specific matching.
    if specific:
        matched_branch = _match_specific_branch(query_norm, city_records or records)
        if matched_branch:
            answer = f"هذا الفرع متاح:\n- {_format_branch_line(matched_branch)}"
            return {
                "matched": True,
                "answer": answer,
                "meta": {
                    "city": _safe_str(matched_branch.get("city")),
                    "branch_name": _safe_str(matched_branch.get("branch_name")),
                    "map_url": _safe_str(matched_branch.get("map_url")),
                },
                "route": "branches_specific",
            }
        if city_records:
            lines = [_format_branch_line(r) for r in city_records[:5]]
            answer = (
                f"في { _safe_str(city_records[0].get('city')) } توجد فروع مثل:\n- "
                + "\n- ".join(lines)
                + "\nلا أقدر أحدد الأقرب بدقة من البيانات الحالية، اذكر الحي أو الموقع التقريبي."
            )
            return {
                "matched": True,
                "answer": answer,
                "meta": {"city": _safe_str(city_records[0].get("city")), "count": len(city_records)},
                "route": "branches_city_list",
            }
        return {
            "matched": False,
            "answer": "أقدر أساعدك بفروع المختبر. اذكر المدينة أو الحي (مثال: الرياض - العليا) عشان أعرض الفروع المتاحة.",
            "meta": {"reason": "needs_city_or_district"},
            "route": "branches_clarify",
        }

    # Generic branches query.
    if generic:
        cities = sorted({_safe_str(r.get("city")) for r in records if _safe_str(r.get("city"))})
        if cities:
            answer = (
                "متوفر لدينا فروع في عدة مدن، مثل: "
                + "، ".join(cities[:8])
                + ".\nاذكر المدينة أو الحي لعرض الفروع الأقرب لك."
            )
        else:
            answer = "متوفر لدينا عدة فروع. اذكر المدينة أو الحي لعرض الفروع المتاحة."
        return {
            "matched": True,
            "answer": answer,
            "meta": {"cities_count": len(cities), "cities": cities[:8]},
            "route": "branches_generic",
        }

    return {"matched": False, "answer": "", "meta": {"reason": "not_branches_intent"}, "route": "branches_no_match"}


if __name__ == "__main__":
    samples = [
        "وين فروعكم",
        "وين أقرب فرع بالرياض",
        "أبي فرع جدة",
        "فرع العليا",
    ]
    for s in samples:
        result = resolve_branches_query(s)
        print(f"INPUT: {s}")
        print(f"MATCHED: {result.get('matched')}")
        print(f"ROUTE: {result.get('route')}")
        print(f"ANSWER: {result.get('answer')}")
        print(f"META: {result.get('meta')}")
        print("-" * 72)
