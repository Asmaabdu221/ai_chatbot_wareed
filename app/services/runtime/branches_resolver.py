"""Deterministic runtime resolver for branches data."""

from __future__ import annotations

import json
import re
import time
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.services.runtime.text_normalizer import normalize_arabic

_PRIMARY_BRANCHES_PATH = Path("app/data/runtime/rag/branches_with_coordinates.jsonl")
_NORMALIZED_BRANCHES_PATH = Path("app/data/runtime/rag/branches_clean.normalized.jsonl")
_LEGACY_BRANCHES_PATH = Path("app/data/runtime/rag/branches_clean.jsonl")

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
_NEAREST_HINTS = ("اقرب", "الاقرب")
_CITY_STOPWORDS = {
    "منطقه",
    "منطقة",
    "فروع",
    "فرع",
    "مختبر",
    "مختبرات",
    "وريد",
    "اقرب",
    "الاقرب",
    "وين",
    "اين",
    "ابي",
    "عندكم",
    "في",
    "بال",
}
_DISTRICT_QUERY_HINTS = ("حي", "الحي", "منطقة", "منطقه", "قريب من", "قريبه من", "بحي")
_CITY_SELECTION_TTL_SECONDS = 15 * 60
_LAST_CITY_SELECTION: dict[str, Any] = {
    "city": "",
    "options": [],
    "updated_at": 0.0,
}


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _normalize_reply_text(text: str) -> str:
    """Normalize spacing/punctuation in branch reply templates only."""
    value = str(text or "").strip()
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"[ ]+\n", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value


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


def _infer_district_from_branch_name(branch_name: str) -> str:
    """Infer district conservatively from branch name when no district exists."""
    branch_norm = normalize_arabic(branch_name)
    if not branch_norm:
        return ""
    tokens = [t for t in branch_norm.split() if t]
    filtered = [t for t in tokens if t not in {"فرع", "الفرع", "الرئيسي", "الرييسي"}]
    if not filtered:
        return ""
    return " ".join(filtered).lstrip("- ").strip()


def _coerce_float(value: Any) -> float | None:
    if value in (None, "", " "):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = _safe_str(value).lower()
    if not text:
        return default
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    return default


def _branches_data_paths() -> list[Path]:
    """Return branches dataset search order with enriched source first."""
    return [
        _PRIMARY_BRANCHES_PATH,
        _NORMALIZED_BRANCHES_PATH,
        _LEGACY_BRANCHES_PATH,
    ]


@lru_cache(maxsize=1)
def load_branches_records() -> list[dict[str, Any]]:
    """Load branches JSONL records with normalized helper fields."""
    source_path = next((p for p in _branches_data_paths() if p.exists()), None)
    if source_path is None:
        return []

    records: list[dict[str, Any]] = []
    with source_path.open("r", encoding="utf-8") as f:
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
            city = _safe_str(row.get("city")) or _extract_city_from_section(section)
            district = _safe_str(row.get("district")) or _infer_district_from_branch_name(branch_name)
            map_url = _safe_str(row.get("maps_url")) or _safe_str(row.get("map_url"))
            latitude = _coerce_float(row.get("latitude"))
            longitude = _coerce_float(row.get("longitude"))
            item = dict(row)
            item["source"] = _safe_str(row.get("source")) or "branches"
            item["id"] = _safe_str(row.get("id"))
            item["is_active"] = _coerce_bool(row.get("is_active"), default=True)
            item["branch_name"] = branch_name
            item["section"] = section
            item["city"] = city
            item["district"] = district
            item["hours"] = _safe_str(row.get("hours"))
            item["maps_url"] = map_url
            item["map_url"] = map_url
            item["latitude"] = latitude
            item["longitude"] = longitude
            item["contact_phone"] = _safe_str(row.get("contact_phone"))
            item["raw_text"] = _safe_str(row.get("raw_text"))
            item["branch_norm"] = normalize_arabic(branch_name)
            item["section_norm"] = normalize_arabic(section)
            item["city_norm"] = normalize_arabic(city)
            item["district_norm"] = normalize_arabic(district)
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


def _is_nearest_query(query_norm: str) -> bool:
    if not query_norm:
        return False
    return any(normalize_arabic(h) in query_norm for h in _NEAREST_HINTS)


def _detect_city(query_norm: str, records: list[dict[str, Any]]) -> str:
    cities = sorted(
        {_safe_str(r.get("city_norm")) for r in records if _safe_str(r.get("city_norm"))},
        key=len,
        reverse=True,
    )
    for city in cities:
        if city and city in query_norm:
            return city
    return ""


def _extract_requested_city_candidate(query_norm: str) -> str:
    """Extract a city-like text from the user query when dataset matching fails."""
    tokens = [t for t in query_norm.split() if t]
    if not tokens:
        return ""

    if "بال" in tokens:
        idx = tokens.index("بال")
        if idx + 1 < len(tokens):
            return tokens[idx + 1]

    if "في" in tokens:
        idx = tokens.index("في")
        if idx + 1 < len(tokens):
            nxt = tokens[idx + 1]
            if nxt in {"مدينة", "مدينه"} and idx + 2 < len(tokens):
                return tokens[idx + 2]
            return nxt

    if "فرع" in tokens:
        idx = tokens.index("فرع")
        if idx + 1 < len(tokens):
            nxt = tokens[idx + 1]
            if nxt not in _CITY_STOPWORDS:
                return nxt

    if any(h in query_norm for h in ("مدينة", "بمدينة")):
        cleaned = [t for t in tokens if t not in _CITY_STOPWORDS]
        if cleaned:
            return cleaned[-1]

    return ""


def _format_branch_name_for_reply(name: str) -> str:
    """Normalize display-only branch naming quirks without changing source data."""
    value = _safe_str(name)
    if value.startswith("فرع الرئيسي -"):
        return value.replace("فرع الرئيسي -", "الفرع الرئيسي -", 1).strip()
    value_norm = normalize_arabic(value)
    if value_norm.startswith("فرع الرئيسي -") or value_norm.startswith("فرع الرييسي -"):
        tail = _safe_str(value.split("-", 1)[1] if "-" in value else "")
        return f"الفرع الرئيسي - {tail}" if tail else "الفرع الرئيسي"
    return value


def _extract_area_candidate(query_norm: str) -> str:
    patterns = (
        r"(?:بحي|حي|الحي)\s+([^\s]+)",
        r"(?:منطقة|منطقه)\s+([^\s]+)",
        r"قريب\s+من\s+([^\s]+)",
        r"قريبه\s+من\s+([^\s]+)",
        r"في\s+حي\s+([^\s]+)",
        r"في\s+([^\s]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, query_norm)
        if match:
            candidate = _safe_str(match.group(1)).strip("-")
            if candidate and candidate not in _CITY_STOPWORDS and candidate not in {"مدينة"}:
                return candidate
    return ""


def _detect_district(query_norm: str, records: list[dict[str, Any]]) -> str:
    if not query_norm:
        return ""

    districts = sorted(
        {_safe_str(r.get("district_norm")) for r in records if _safe_str(r.get("district_norm"))},
        key=len,
        reverse=True,
    )
    for district in districts:
        if district and district in query_norm:
            return district

    candidate = _extract_area_candidate(query_norm)
    if not candidate:
        return ""

    for district in districts:
        if district == candidate:
            return district
    for district in districts:
        if district and (candidate in district or district in candidate):
            return district

    best = ""
    best_score = 0.0
    for district in districts:
        score = SequenceMatcher(None, candidate, district).ratio()
        if score > best_score:
            best_score = score
            best = district
    if best and best_score >= 0.84:
        return best
    return ""


def _find_district_matches(
    district_norm: str,
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not district_norm:
        return []
    exact = [r for r in records if _safe_str(r.get("district_norm")) == district_norm]
    if exact:
        return exact
    contains = [
        r
        for r in records
        if _safe_str(r.get("district_norm"))
        and (
            district_norm in _safe_str(r.get("district_norm"))
            or _safe_str(r.get("district_norm")) in district_norm
        )
    ]
    if contains:
        return contains
    scored: list[tuple[float, dict[str, Any]]] = []
    for record in records:
        district = _safe_str(record.get("district_norm"))
        if not district:
            continue
        score = SequenceMatcher(None, district_norm, district).ratio()
        if score >= 0.84:
            scored.append((score, record))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [record for _, record in scored[:5]]


def _format_branch_card(prefix: str, record: dict[str, Any]) -> str:
    name = _format_branch_name_for_reply(_safe_str(record.get("branch_name")))
    city = _safe_str(record.get("city"))
    hours = _safe_str(record.get("hours"))
    map_url = _safe_str(record.get("map_url"))
    lines = [prefix, "", f"{name} – {city}" if city else name]
    if hours:
        lines.append(hours)
    if map_url:
        lines.append(f"رابط الموقع: {map_url}")
    return _normalize_reply_text("\n".join(lines))


def _format_district_options(matches: list[dict[str, Any]]) -> str:
    options: list[str] = []
    for record in matches[:3]:
        name = _format_branch_name_for_reply(_safe_str(record.get("branch_name")))
        city = _safe_str(record.get("city"))
        options.append(f"- {name} – {city}" if city else f"- {name}")
    return _normalize_reply_text(
        "لقيت أكثر من خيار في هذا الحي، مثل:\n"
        + "\n".join(options)
        + "\n\nإذا تحدد المدينة أو موقعك التقريبي أقدر أحدد لك الأقرب."
    )


def _set_last_city_options(city: str, options: list[dict[str, Any]]) -> None:
    _LAST_CITY_SELECTION["city"] = _safe_str(city)
    _LAST_CITY_SELECTION["options"] = list(options or [])
    _LAST_CITY_SELECTION["updated_at"] = time.time()


def _get_last_city_option(selection_number: int) -> dict[str, Any] | None:
    if selection_number < 1:
        return None
    updated_at = float(_LAST_CITY_SELECTION.get("updated_at") or 0.0)
    if not updated_at or (time.time() - updated_at) > _CITY_SELECTION_TTL_SECONDS:
        return None
    options = list(_LAST_CITY_SELECTION.get("options") or [])
    index = selection_number - 1
    if index < 0 or index >= len(options):
        return None
    return options[index]


def _parse_numeric_selection(text: str) -> int | None:
    value = _safe_str(text)
    if not value:
        return None

    normalized_digits = value.translate(
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
    if not re.fullmatch(r"\d{1,2}", normalized_digits):
        return None
    try:
        return int(normalized_digits)
    except ValueError:
        return None


def _format_generic_branches_reply() -> str:
    return _normalize_reply_text(
        (
        "عندنا أكثر من 60 فرع حول المملكة في مدن مثل الرياض وجدة والشرقية والمدينة وغيرها.\n\n"
        "إذا تعطيني اسم المدينة، أقدر أطلع لك الفروع المتاحة فيها."
        )
    )


def _format_city_reply(city: str, city_records: list[dict[str, Any]]) -> str:
    names: list[str] = []
    city_options: list[dict[str, Any]] = []
    for record in city_records:
        name = _format_branch_name_for_reply(_safe_str(record.get("branch_name")))
        if name and name not in names:
            names.append(name)
            city_options.append(record)
    _set_last_city_options(city, city_options)

    lines = [f"أكيد، هذه الفروع المتاحة في {city}:"]
    for idx, branch_name in enumerate(names, start=1):
        lines.append(f"{idx}) {branch_name}")
    lines.append("اختر الرقم الأقرب أو المناسب لك، وأرسل لك رابط الموقع.")
    return _normalize_reply_text(
        "\n".join(lines)
    )


def _format_nearest_city_clarification(city: str) -> str:
    return _normalize_reply_text(
        (
            f"عندنا أكثر من فرع في مدينة {city}.\n\n"
            "لتحديد أقرب فرع لك، ممكن تزودني بالمنطقة أو الحي اللي أنت فيه أو موقعك التقريبي."
        )
    )


def _format_city_not_found_reply() -> str:
    return _normalize_reply_text(
        (
        "بهذه المدينة مع الأسف لا يوجد لدينا فروع حاليًا.\n\n"
        "اكتب لي اسم المدينة الأقرب لك، وأساعدك بتحديد أقرب فرع."
        )
    )


def _format_direct_branch_reply(record: dict[str, Any]) -> str:
    return _format_branch_card("نعم، هذا الفرع متوفر:", record)


def _format_selected_branch_reply(record: dict[str, Any]) -> str:
    name = _format_branch_name_for_reply(_safe_str(record.get("branch_name")))
    city = _safe_str(record.get("city"))
    hours = _safe_str(record.get("hours"))
    map_url = _safe_str(record.get("map_url")) or _safe_str(record.get("maps_url"))
    phone = _safe_str(record.get("contact_phone"))

    lines = ["هذا الفرع:", f"{name} – {city}" if city else name]
    if hours:
        lines.append(f"الدوام: {hours}")
    if map_url:
        lines.append(f"الموقع: {map_url}")
    if phone:
        lines.append(f"رقم التواصل: {phone}")
    return _normalize_reply_text("\n".join(lines))


def _format_unknown_area_reply() -> str:
    return _normalize_reply_text(
        "لا يوجد لدينا فرع مطابق بهذا الاسم في البيانات الحالية.\n"
        "إذا ممكن تعطيني اسم المدينة التي أنت فيها، أقدر أرسل لك الفروع المتاحة فيها."
    )


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
    """Resolve branches query from branches runtime dataset only."""
    query = _safe_str(user_text)
    query_norm = normalize_arabic(query)
    if not query_norm:
        return {"matched": False, "answer": "", "meta": {"reason": "empty_query"}, "route": "branches_no_match"}

    records = [r for r in load_branches_records() if bool(r.get("is_active", True))]
    if not records:
        records = load_branches_records()
    if not records:
        return {"matched": False, "answer": "", "meta": {"reason": "branches_data_unavailable"}, "route": "branches_no_match"}

    city_norm = _detect_city(query_norm, records)
    city_records = [r for r in records if city_norm and _safe_str(r.get("city_norm")) == city_norm]
    district_norm = _detect_district(query_norm, records)

    specific = _is_specific_branches_query(query_norm)
    generic = _is_generic_branches_query(query_norm)
    nearest = _is_nearest_query(query_norm)
    requested_city_candidate = _extract_requested_city_candidate(query_norm)
    area_candidate = _extract_area_candidate(query_norm)

    numeric_selection = _parse_numeric_selection(query_norm)
    if numeric_selection is not None:
        selected = _get_last_city_option(numeric_selection)
        if selected:
            return {
                "matched": True,
                "answer": _format_selected_branch_reply(selected),
                "meta": {
                    "id": _safe_str(selected.get("id")),
                    "source": _safe_str(selected.get("source")),
                    "city": _safe_str(selected.get("city")),
                    "district": _safe_str(selected.get("district")),
                    "branch_name": _safe_str(selected.get("branch_name")),
                    "map_url": _safe_str(selected.get("map_url")),
                    "maps_url": _safe_str(selected.get("maps_url")),
                    "contact_phone": _safe_str(selected.get("contact_phone")),
                    "latitude": selected.get("latitude"),
                    "longitude": selected.get("longitude"),
                    "from_city_numbered_selection": True,
                    "selection_number": numeric_selection,
                },
                "route": "branches_city_number_selection",
            }

    # 1) Generic branches query.
    if generic and not city_records and not district_norm and not nearest:
        return {
            "matched": True,
            "answer": _format_generic_branches_reply(),
            "meta": {
                "cities_count": len({_safe_str(r.get("city")) for r in records if _safe_str(r.get("city"))}),
            },
            "route": "branches_generic",
        }

    # 2) Direct branch-name query.
    matched_branch = None
    if "فرع" in query_norm or specific:
        matched_branch = _match_specific_branch(query_norm, city_records or records)
        if matched_branch and _safe_str(matched_branch.get("branch_norm")) in query_norm:
            return {
                "matched": True,
                "answer": _format_direct_branch_reply(matched_branch),
                "meta": {
                    "id": _safe_str(matched_branch.get("id")),
                    "source": _safe_str(matched_branch.get("source")),
                    "city": _safe_str(matched_branch.get("city")),
                    "district": _safe_str(matched_branch.get("district")),
                    "branch_name": _safe_str(matched_branch.get("branch_name")),
                    "map_url": _safe_str(matched_branch.get("map_url")),
                    "latitude": matched_branch.get("latitude"),
                    "longitude": matched_branch.get("longitude"),
                },
                "route": "branches_specific",
            }

    # 3) Nearest in city with no district/location.
    if city_records and nearest and not district_norm:
        city = _safe_str(city_records[0].get("city"))
        return {
            "matched": True,
            "answer": _format_nearest_city_clarification(city),
            "meta": {"city": city, "count": len(city_records), "nearest_requested": True},
            "route": "branches_city_list",
        }

    # 4) City-only request.
    city_request_tokens = ("فرع" in query_norm or "فروع" in query_norm or "مدينه" in query_norm or "مدينة" in query_norm)
    if city_records and (city_request_tokens or specific or generic or query_norm == city_norm):
        city = _safe_str(city_records[0].get("city"))
        return {
            "matched": True,
            "answer": _format_city_reply(city, city_records),
            "meta": {"city": city, "count": len(city_records), "nearest_requested": nearest},
            "route": "branches_city_list",
        }

    # 5) District-like request.
    district_like = district_norm or any(hint in query_norm for hint in _DISTRICT_QUERY_HINTS) or bool(area_candidate)
    if district_like:
        scoped_records = city_records if city_records else records
        district_matches = _find_district_matches(district_norm, scoped_records) if district_norm else []
        if len(district_matches) == 1:
            record = district_matches[0]
            return {
                "matched": True,
                "answer": _format_branch_card("الأقرب لك في هذا الحي هو:", record),
                "meta": {
                    "id": _safe_str(record.get("id")),
                    "source": _safe_str(record.get("source")),
                    "city": _safe_str(record.get("city")),
                    "district": _safe_str(record.get("district")),
                    "branch_name": _safe_str(record.get("branch_name")),
                    "map_url": _safe_str(record.get("map_url")),
                    "latitude": record.get("latitude"),
                    "longitude": record.get("longitude"),
                    "from_district_match": True,
                },
                "route": "branches_district_match",
            }
        if len(district_matches) > 1:
            return {
                "matched": True,
                "answer": _format_district_options(district_matches),
                "meta": {
                    "count": len(district_matches),
                    "district_norm": district_norm,
                    "city": _safe_str(city_records[0].get("city")) if city_records else "",
                },
                "route": "branches_district_options",
            }
        return {
            "matched": True,
            "answer": _format_unknown_area_reply(),
            "meta": {"reason": "unknown_area_or_district"},
            "route": "branches_unknown_area",
        }

    # City not found fallback for branch/city intents.
    branch_city_intent = specific or generic or nearest or "فرع" in query_norm or "فروع" in query_norm
    if branch_city_intent and not city_records and requested_city_candidate and requested_city_candidate not in {"", "حي", "منطقه", "منطقة"}:
        return {
            "matched": True,
            "answer": _format_city_not_found_reply(),
            "meta": {"requested_city": requested_city_candidate, "reason": "city_not_found"},
            "route": "branches_city_not_found",
        }

    # Keep existing safe clarification behavior for branch-intent queries.
    if specific:
        return {
            "matched": False,
            "answer": "أقدر أساعدك بفروع المختبر. اذكر المدينة أو الحي (مثال: الرياض - العليا) عشان أعرض الفروع المتاحة.",
            "meta": {"reason": "needs_city_or_district"},
            "route": "branches_clarify",
        }

    # Generic branches fallback.
    if generic:
        return {
            "matched": True,
            "answer": _format_generic_branches_reply(),
            "meta": {
                "cities_count": len({_safe_str(r.get("city")) for r in records if _safe_str(r.get("city"))}),
            },
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
