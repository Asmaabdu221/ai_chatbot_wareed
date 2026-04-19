"""Deterministic runtime resolver for branches data."""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID

from app.services.runtime.entity_memory import load_entity_memory
from app.services.runtime.selection_state import load_selection_state, save_selection_state
from app.services.runtime.text_normalizer import normalize_arabic

_PRIMARY_BRANCHES_PATH = Path("app/data/runtime/rag/branches_clean.jsonl")
_NORMALIZED_BRANCHES_PATH = Path("app/data/runtime/rag/branches_with_coordinates.jsonl")
_LEGACY_BRANCHES_PATH = Path("app/data/runtime/rag/branches_clean.normalized.jsonl")

_GENERIC_BRANCHES_HINTS = (
    "فروعكم",
    "فروع",
    "اين تتواجد",
    "وين فروع",
    "ايش عندكم فروع",
    "وش عندكم فروع",
    "وين فروعكم",
    "موقعكم",
    "عنوانكم",
)
_SPECIFIC_BRANCH_HINTS = (
    "اقرب",
    "الاقرب",
    "فرع",
    "فرع في",
    "ابي اقرب فرع",
    "ابغى اقرب فرع",
    "وين اقرب فرع",
    "عندكم فرع في",
    "موقع فرع",
    "دوام فرع",
    "رقم فرع",
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
_DIRECTIONAL_TOKENS = ("شمال", "جنوب", "شرق", "غرب", "وسط", "شمالي", "جنوبي", "شرقي", "غربي")
_CITY_CANONICAL_ALIASES = {
    "الرياض": "الرياض",
    "رياض": "الرياض",
    "جده": "جدة",
    "جدة": "جدة",
    "مكه": "مكة المكرمة",
    "مكة": "مكة المكرمة",
    "مكه المكرمه": "مكة المكرمة",
    "مكة المكرمة": "مكة المكرمة",
    "الطايف": "الطائف",
    "الطائف": "الطائف",
}
_CITY_ALIAS_NORMS = {
    normalize_arabic(alias) for alias in _CITY_CANONICAL_ALIASES.keys()
} | {
    normalize_arabic(city) for city in _CITY_CANONICAL_ALIASES.values()
}
_BRANCH_QUERY_TYPES = {
    "numeric_selection",
    "direct_branch",
    "district_query",
    "unknown_branch_area",
    "nearest_city",
    "city_query",
    "city_not_found",
    "specific_clarify",
    "generic_overview",
    "no_match",
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


def _normalize_city_token(token: str) -> str:
    """Normalize one city-like token with conservative Arabic preposition stripping."""
    value = normalize_arabic(_safe_str(token))
    if not value:
        return ""

    if value.startswith("بال") and len(value) > 3:
        value = value[3:]
    elif value.startswith("ب") and len(value) > 2 and value[1] != "ا":
        value = value[1:]
    elif value.startswith("في") and len(value) > 3:
        value = value[2:]

    value = value.strip()
    canonical = _safe_str(_CITY_CANONICAL_ALIASES.get(value, value))
    return normalize_arabic(canonical)


def _build_city_lookup(records: list[dict[str, Any]]) -> dict[str, str]:
    """Build normalized city alias lookup -> dataset city_norm."""
    lookup: dict[str, str] = {}
    for record in records:
        city = _safe_str(record.get("city"))
        city_norm = _safe_str(record.get("city_norm"))
        if not city_norm:
            continue

        keys = {
            city_norm,
            _normalize_city_token(city),
        }
        if city_norm.startswith("ال") and len(city_norm) > 2:
            keys.add(city_norm[2:])

        for alias_key, canonical_city in _CITY_CANONICAL_ALIASES.items():
            alias_norm = normalize_arabic(alias_key)
            canonical_norm = normalize_arabic(canonical_city)
            if canonical_norm == city_norm:
                keys.add(alias_norm)
                keys.add(_normalize_city_token(alias_norm))

        for key in keys:
            clean = _safe_str(key)
            if clean:
                lookup[clean] = city_norm
    return lookup


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
            map_url = (
                _safe_str(row.get("location_url"))
                or _safe_str(row.get("maps_url"))
                or _safe_str(row.get("map_url"))
            )
            address = _safe_str(row.get("address")) or _safe_str(row.get("raw_text"))
            working_hours = _safe_str(row.get("working_hours")) or _safe_str(row.get("hours"))
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
            item["hours"] = working_hours
            item["working_hours"] = working_hours
            item["address"] = address
            item["location_url"] = map_url
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
    lookup = _build_city_lookup(records)

    # 1) direct lookup key containment with boundaries.
    for key, city_norm in sorted(lookup.items(), key=lambda x: len(x[0]), reverse=True):
        if not key:
            continue
        if query_norm == key or f" {key} " in f" {query_norm} ":
            return city_norm

    # 2) fallback full-city containment (existing behavior).
    cities = sorted(
        {_safe_str(r.get("city_norm")) for r in records if _safe_str(r.get("city_norm"))},
        key=len,
        reverse=True,
    )
    for city in cities:
        if city and city in query_norm:
            return city

    # 3) token and bigram-based city candidate matching.
    tokens = [t for t in query_norm.split() if t]
    for token in tokens:
        normalized_token = _normalize_city_token(token)
        if normalized_token in lookup:
            return lookup[normalized_token]

    for i in range(len(tokens) - 1):
        bigram = f"{tokens[i]} {tokens[i + 1]}"
        normalized_bigram = _normalize_city_token(bigram)
        if normalized_bigram in lookup:
            return lookup[normalized_bigram]

    return ""


def _extract_requested_city_candidate(query_norm: str) -> str:
    """Extract a city-like text from the user query when dataset matching fails."""
    tokens = [t for t in query_norm.split() if t]
    if not tokens:
        return ""

    # Attached prepositions: بالرياض / بجدة / بالمدينه / بمكة
    for token in tokens:
        normalized_token = _normalize_city_token(token)
        if normalized_token and normalized_token != normalize_arabic(token):
            return normalized_token

    if "بال" in tokens:
        idx = tokens.index("بال")
        if idx + 1 < len(tokens):
            return _normalize_city_token(tokens[idx + 1]) or tokens[idx + 1]

    if "في" in tokens:
        idx = tokens.index("في")
        if idx + 1 < len(tokens):
            nxt = tokens[idx + 1]
            if nxt in {"مدينة", "مدينه"} and idx + 2 < len(tokens):
                return _normalize_city_token(tokens[idx + 2]) or tokens[idx + 2]
            return _normalize_city_token(nxt) or nxt

    if "فرع" in tokens:
        idx = tokens.index("فرع")
        if idx + 1 < len(tokens):
            nxt = tokens[idx + 1]
            if nxt not in _CITY_STOPWORDS:
                return _normalize_city_token(nxt) or nxt

    if any(h in query_norm for h in ("مدينة", "بمدينة")):
        cleaned = [t for t in tokens if t not in _CITY_STOPWORDS]
        if cleaned:
            return _normalize_city_token(cleaned[-1]) or cleaned[-1]

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


def _extract_area_candidate(query_norm: str, *, allow_single_word: bool = False) -> str:
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
    if allow_single_word:
        tokens = [t for t in query_norm.split() if t]
        if len(tokens) == 1:
            token = _safe_str(tokens[0]).strip("-")
            if (
                token
                and token not in _CITY_STOPWORDS
                and normalize_arabic(_normalize_city_token(token)) not in _CITY_ALIAS_NORMS
                and token not in _DIRECTIONAL_TOKENS
            ):
                return token
    return ""


def _detect_district(query_norm: str, records: list[dict[str, Any]], *, allow_single_word: bool = False) -> str:
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

    candidate = _extract_area_candidate(query_norm, allow_single_word=allow_single_word)
    if not candidate:
        return ""
    # Directional phrases (e.g. "شمال الرياض") should not be treated as district names.
    if any(candidate.startswith(d) for d in _DIRECTIONAL_TOKENS):
        return ""
    if normalize_arabic(_normalize_city_token(candidate)) in _CITY_ALIAS_NORMS:
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


def _has_valid_city_selection_state(conversation_id: UUID | None) -> bool:
    state = load_selection_state(conversation_id)
    if _safe_str(state.get("last_selection_type")) != "branch":
        return False
    return bool(list(state.get("last_options") or []))


def _get_last_city_option(selection_number: int, conversation_id: UUID | None) -> dict[str, Any] | None:
    if selection_number < 1:
        return None
    state = load_selection_state(conversation_id)
    if _safe_str(state.get("last_selection_type")) != "branch":
        return None
    options = list(state.get("last_options") or [])
    index = selection_number - 1
    if index < 0 or index >= len(options):
        return None
    selected = options[index]
    if not isinstance(selected, dict):
        return None
    payload = selected.get("selection_payload")
    if isinstance(payload, dict):
        return payload
    return selected


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
            "لدينا أكثر من 60 فرع حول المملكة.\n\n"
            "أرسل لي اسم المدينة، مثل: الرياض أو جدة، وبعطيك الفروع المتاحة فيها."
        )
    )


def _get_all_available_cities(records: list[dict[str, Any]]) -> list[str]:
    return sorted({_safe_str(r.get("city")) for r in records if _safe_str(r.get("city"))})


def _format_available_cities(records: list[dict[str, Any]]) -> str:
    cities = _get_all_available_cities(records)
    if not cities:
        return "-"
    return "\n".join(f"- {city}" for city in cities)


def _format_city_reply(city: str, city_records: list[dict[str, Any]], conversation_id: UUID | None = None) -> str:
    names: list[str] = []
    city_options: list[dict[str, Any]] = []
    for record in city_records:
        name = _format_branch_name_for_reply(_safe_str(record.get("branch_name")))
        if name and name not in names:
            names.append(name)
            city_options.append(record)
    if conversation_id is not None and city_options:
        options_payload = [
            {
                "id": _safe_str(record.get("id")) or f"branch::{idx}",
                "label": _format_branch_name_for_reply(_safe_str(record.get("branch_name"))),
                "selection_payload": dict(record),
            }
            for idx, record in enumerate(city_options, start=1)
        ]
        save_selection_state(
            conversation_id,
            options=options_payload,
            selection_type="branch",
            city=city,
        )

    lines = [f"هذه الفروع المتاحة في {city}:", ""]
    for idx, branch_name in enumerate(names, start=1):
        lines.append(f"{idx}) {branch_name}")
    lines.append("")
    lines.append("اختر رقم أو اسم الفرع، وبعطيك الموقع.")
    return _normalize_reply_text("\n".join(lines))


def _is_short_locality_refinement_query(query_norm: str) -> bool:
    if not query_norm:
        return False
    words = [w for w in query_norm.split() if w]
    if not (1 <= len(words) <= 3):
        return False
    if re.search(r"[a-zA-Z0-9]", query_norm):
        return False
    blocked = {"نعم", "ايوا", "ايوه", "تمام", "اوكي", "ok", "وش", "ايش", "ما", "متى", "كيف", "كم", "سعر", "باقة", "تحليل"}
    if any(w in blocked for w in words):
        return False
    return True


def _extract_city_from_directional_phrase(query_norm: str, records: list[dict[str, Any]]) -> str:
    words = [w for w in query_norm.split() if w]
    if len(words) < 2:
        return ""
    if words[0] not in _DIRECTIONAL_TOKENS:
        return ""
    tail = " ".join(words[1:]).strip()
    if not tail:
        return ""
    return _detect_city(tail, records)


def _get_recent_branch_city_context(conversation_id: UUID | None) -> str:
    if conversation_id is None:
        return ""
    state = load_selection_state(conversation_id)
    if _safe_str(state.get("last_selection_type")) == "branch":
        # Selection state persists city under "last_city"; keep "city" as a legacy fallback.
        city_from_state = _safe_str(state.get("last_city")) or _safe_str(state.get("city"))
        if city_from_state:
            return normalize_arabic(city_from_state)
    memory = load_entity_memory(conversation_id)
    if _safe_str(memory.get("last_intent")) != "branch":
        return ""
    city_from_memory = _safe_str((memory.get("last_branch") or {}).get("city"))
    if city_from_memory:
        return normalize_arabic(city_from_memory)
    return ""


def _format_nearest_city_clarification(city: str) -> str:
    return _normalize_reply_text(
        (
            f"عندنا أكثر من فرع في مدينة {city}.\n\n"
            "لتحديد أقرب فرع لك، ممكن تزودني بالمنطقة أو الحي اللي أنت فيه أو موقعك التقريبي."
        )
    )


def _format_city_not_found_reply(records: list[dict[str, Any]]) -> str:
    return _normalize_reply_text(
        (
            "حالياً لا يوجد لدينا فروع في هذه المدينة.\n\n"
            "المدن المتاحة لدينا:\n"
            f"{_format_available_cities(records)}\n\n"
            "أرسل اسم المدينة من القائمة، وبعطيك الفروع."
        )
    )


def _format_direct_branch_reply(record: dict[str, Any]) -> str:
    return _format_branch_card("نعم، هذا الفرع متوفر:", record)


def _format_selected_branch_reply(record: dict[str, Any]) -> str:
    name = _format_branch_name_for_reply(_safe_str(record.get("branch_name")))
    display_name = name if name.startswith("فرع") else f"فرع {name}"
    address = _safe_str(record.get("address")) or "غير متوفر حالياً"
    location_url = (
        _safe_str(record.get("location_url"))
        or _safe_str(record.get("map_url"))
        or _safe_str(record.get("maps_url"))
        or "غير متوفر حالياً"
    )
    hours = _safe_str(record.get("working_hours")) or _safe_str(record.get("hours")) or "غير متوفر حالياً"

    lines = [
        display_name,
        "",
        f"العنوان: {address}",
        f"الموقع: {location_url}",
        f"ساعات العمل: {hours}",
        "رقم الهاتف: 8001221220",
    ]
    return _normalize_reply_text("\n".join(lines))


def _format_unknown_area_reply(records: list[dict[str, Any]]) -> str:
    return _normalize_reply_text(
        "حالياً لا يوجد لدينا فروع في هذه المدينة.\n\n"
        "المدن المتاحة لدينا:\n"
        f"{_format_available_cities(records)}\n\n"
        "أرسل اسم المدينة من القائمة، وبعطيك الفروع."
    )


def _find_last_city_option_by_name(text: str, conversation_id: UUID | None) -> dict[str, Any] | None:
    if conversation_id is None:
        return None
    query_norm = normalize_arabic(_safe_str(text))
    if not query_norm:
        return None
    state = load_selection_state(conversation_id)
    if _safe_str(state.get("last_selection_type")) != "branch":
        return None
    options = list(state.get("last_options") or [])
    for option in options:
        if not isinstance(option, dict):
            continue
        payload = option.get("selection_payload") if isinstance(option.get("selection_payload"), dict) else option
        label = _safe_str(option.get("label")) or _safe_str(payload.get("branch_name"))
        label_norm = normalize_arabic(label)
        if not label_norm:
            continue
        if query_norm == label_norm or query_norm in label_norm or label_norm in query_norm:
            return payload
    return None


def _enrich_meta(
    meta: dict[str, Any] | None,
    *,
    query_type: str,
    has_state: bool,
    matched_branch_id: str = "",
) -> dict[str, Any]:
    payload = dict(meta or {})
    payload["query_type"] = query_type
    payload["has_state"] = bool(has_state)
    payload["matched_branch_id"] = _safe_str(matched_branch_id)
    return payload


def classify_branch_query_type(
    *,
    numeric_selection: int | None,
    has_numeric_option: bool,
    has_direct_branch_match: bool,
    district_like: bool,
    district_match_count: int,
    has_city_records: bool,
    nearest: bool,
    city_query_like: bool,
    generic: bool,
    specific: bool,
    has_requested_city_candidate: bool,
) -> str:
    """Classify branch query into one explicit deterministic query type."""
    if numeric_selection is not None and has_numeric_option:
        return "numeric_selection"

    if has_direct_branch_match:
        return "direct_branch"

    if district_like:
        if district_match_count > 0:
            return "district_query"
        return "unknown_branch_area"

    if has_city_records and nearest:
        return "nearest_city"

    if has_city_records and (city_query_like or specific or generic):
        return "city_query"

    if (specific or generic or nearest or city_query_like) and (not has_city_records) and has_requested_city_candidate:
        return "city_not_found"

    if specific:
        return "specific_clarify"

    if generic and (not district_like) and (not has_city_records) and (not nearest):
        return "generic_overview"

    return "no_match"


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


def resolve_branches_query(user_text: str, conversation_id: UUID | None = None) -> dict[str, Any]:
    """Resolve branches query using deterministic 3-step flow."""
    query = _safe_str(user_text)
    query_norm = normalize_arabic(query)
    if not query_norm:
        return {
            "matched": False,
            "answer": "",
            "meta": _enrich_meta({"reason": "empty_query"}, query_type="no_match", has_state=False),
            "route": "branches_no_match",
        }

    records = [r for r in load_branches_records() if bool(r.get("is_active", True))]
    if not records:
        records = load_branches_records()
    if not records:
        return {
            "matched": True,
            "answer": _format_generic_branches_reply(),
            "meta": _enrich_meta(
                {"reason": "branches_data_unavailable"},
                query_type="generic_overview",
                has_state=False,
            ),
            "route": "branches_generic",
        }

    has_state = _has_valid_city_selection_state(conversation_id)
    generic = _is_generic_branches_query(query_norm)
    specific = _is_specific_branches_query(query_norm)
    city_norm = _detect_city(query_norm, records)
    city_records = [r for r in records if city_norm and _safe_str(r.get("city_norm")) == city_norm]
    requested_city_candidate = _extract_requested_city_candidate(query_norm)
    has_branch_anchor = any(t in query_norm for t in ("فرع", "فروع", "الموقع", "العنوان", "موقع"))
    tokens = [t for t in query_norm.split() if t]
    is_city_only_query = bool(
        1 <= len(tokens) <= 3
        and not any(t in query_norm for t in ("فرع", "فروع", "الموقع", "العنوان", "باقة", "تحليل"))
        and re.search(r"[0-9]", query_norm) is None
    )
    is_branch_domain_query = bool(
        generic
        or specific
        or has_branch_anchor
        or city_norm
        or (has_state and (is_city_only_query or _parse_numeric_selection(query_norm) is not None))
    )
    if not is_branch_domain_query:
        return {
            "matched": False,
            "answer": "",
            "meta": _enrich_meta({"reason": "not_branches_intent"}, query_type="no_match", has_state=has_state),
            "route": "branches_no_match",
        }

    # STEP 3 (selection): numeric
    numeric_selection = _parse_numeric_selection(query_norm)
    selected = _get_last_city_option(numeric_selection, conversation_id) if numeric_selection is not None else None
    if numeric_selection is not None:
        if selected is not None:
            selected_id = _safe_str(selected.get("id"))
            return {
                "matched": True,
                "answer": _format_selected_branch_reply(selected),
                "meta": _enrich_meta(
                    {
                        "id": selected_id,
                        "city": _safe_str(selected.get("city")),
                        "branch_name": _safe_str(selected.get("branch_name")),
                        "selection_number": numeric_selection,
                    },
                    query_type="numeric_selection",
                    has_state=has_state,
                    matched_branch_id=selected_id,
                ),
                "route": "branches_city_number_selection",
            }
        return {
            "matched": True,
            "answer": _format_generic_branches_reply(),
            "meta": _enrich_meta(
                {"reason": "numeric_without_state"},
                query_type="generic_overview",
                has_state=has_state,
            ),
            "route": "branches_generic",
        }

    # STEP 3 (selection): by name from last listed city options.
    selected_by_name = _find_last_city_option_by_name(query, conversation_id)
    if selected_by_name is not None:
        selected_id = _safe_str(selected_by_name.get("id"))
        return {
            "matched": True,
            "answer": _format_selected_branch_reply(selected_by_name),
            "meta": _enrich_meta(
                {
                    "id": selected_id,
                    "city": _safe_str(selected_by_name.get("city")),
                    "branch_name": _safe_str(selected_by_name.get("branch_name")),
                    "from_state_name_selection": True,
                },
                query_type="name_selection",
                has_state=has_state,
                matched_branch_id=selected_id,
            ),
            "route": "branches_city_name_selection",
        }

    # STEP 3 (direct branch): global branch-name match, e.g. "فرع العليا".
    matched_branch = None
    if specific or has_branch_anchor:
        query_branch_tail = _safe_str(query_norm.replace("فرع", ""))
        if query_branch_tail:
            strong_tail_matches = [
                r
                for r in records
                if (
                    query_branch_tail in _safe_str(r.get("branch_norm"))
                    or query_branch_tail in _safe_str(r.get("district_norm"))
                    or query_branch_tail in _safe_str(r.get("raw_norm"))
                )
            ]
            if len(strong_tail_matches) == 1:
                matched_branch = strong_tail_matches[0]
        if matched_branch is None:
            matched_branch = _match_specific_branch(query_norm, records)
    if matched_branch is not None:
        matched_id = _safe_str(matched_branch.get("id"))
        return {
            "matched": True,
            "answer": _format_selected_branch_reply(matched_branch),
            "meta": _enrich_meta(
                {
                    "id": matched_id,
                    "city": _safe_str(matched_branch.get("city")),
                    "branch_name": _safe_str(matched_branch.get("branch_name")),
                },
                query_type="direct_branch",
                has_state=has_state,
                matched_branch_id=matched_id,
            ),
            "route": "branches_specific",
        }

    # STEP 2: city exists -> list branches for city.
    if city_records:
        city = _safe_str(city_records[0].get("city"))
        return {
            "matched": True,
            "answer": _format_city_reply(city, city_records, conversation_id),
            "meta": _enrich_meta(
                {"city": city, "count": len(city_records)},
                query_type="city_query",
                has_state=has_state,
            ),
            "route": "branches_city_list",
        }

    # STEP 2: city not found -> show full cities list from dataset.
    if requested_city_candidate or is_city_only_query:
        return {
            "matched": True,
            "answer": _format_city_not_found_reply(records),
            "meta": _enrich_meta(
                {
                    "requested_city": requested_city_candidate,
                    "reason": "city_not_found",
                },
                query_type="city_not_found",
                has_state=has_state,
            ),
            "route": "branches_city_not_found",
        }

    # STEP 1: generic branches overview.
    if conversation_id is not None:
        save_selection_state(
            conversation_id,
            options=[],
            selection_type="branch",
            city="",
            query_type="generic_overview",
        )
    return {
        "matched": True,
        "answer": _format_generic_branches_reply(),
        "meta": _enrich_meta(
            {
                "cities_count": len(_get_all_available_cities(records)),
                "followup_anchor": "branch_generic_overview",
            },
            query_type="generic_overview",
            has_state=has_state,
        ),
        "route": "branches_generic",
    }
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


