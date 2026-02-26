"""
Deterministic packages index service.

This module is pure data lookup logic (no LLM usage).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

INDEX_PATH = Path(__file__).resolve().parent / "packages_index.json"

_PACKAGES_CACHE: Optional[list[dict[str, Any]]] = None
_PREPARED_CACHE: Optional[list[dict[str, Any]]] = None

_REQUIRED_KEYS = {
    "id",
    "row",
    "section",
    "name_raw",
    "name_norm",
    "description_raw",
    "price_raw",
    "aliases",
}

_DIACRITICS_RE = re.compile(r"[\u064B-\u065F\u0670]")
_PUNCT_RE = re.compile(r"[^\w\s\u0600-\u06FF]")
_WS_RE = re.compile(r"\s+")
_EN_TOKEN_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9/-]*\b")

_DIGIT_TRANSLATION = str.maketrans(
    "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹",
    "01234567890123456789",
)

_DETAIL_KEYWORDS = (
    "تشمل",
    "يُستخدم",
    "يستخدم",
    "يساعد",
    "يفيد",
    "مناسب",
    "مدة النتائج",
    "نوع العينة",
)


def load_packages_index() -> list[dict[str, Any]]:
    """Load and validate packages index with module-level caching."""
    global _PACKAGES_CACHE
    if _PACKAGES_CACHE is not None:
        return _PACKAGES_CACHE

    if not INDEX_PATH.exists():
        raise FileNotFoundError(f"Packages index not found: {INDEX_PATH}")

    data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("packages_index.json must contain a list")

    validated: list[dict[str, Any]] = []
    for i, record in enumerate(data):
        if not isinstance(record, dict):
            raise ValueError(f"Record at index {i} is not an object")
        missing = _REQUIRED_KEYS - set(record.keys())
        if missing:
            raise ValueError(
                f"Record at index {i} missing required keys: {sorted(missing)}"
            )
        validated.append(record)

    _PACKAGES_CACHE = validated
    return validated


def normalize_query(text: str) -> str:
    """Normalize Arabic/English query text for deterministic matching."""
    value = "" if text is None else str(text)
    value = value.replace("\u00a0", " ")
    value = _DIACRITICS_RE.sub("", value)
    value = value.replace("ـ", "")
    value = value.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    value = value.replace("ى", "ي")
    value = value.replace("ة", "ه")
    value = value.replace("ئ", "ي")
    value = value.replace("ؤ", "و")
    value = value.translate(_DIGIT_TRANSLATION)
    value = value.lower()
    value = _PUNCT_RE.sub(" ", value)
    value = _WS_RE.sub(" ", value).strip()
    return value


def _prepare_records() -> list[dict[str, Any]]:
    global _PREPARED_CACHE
    if _PREPARED_CACHE is not None:
        return _PREPARED_CACHE

    prepared: list[dict[str, Any]] = []
    for rec in load_packages_index():
        name_norm = normalize_query(rec.get("name_norm") or rec.get("name_raw") or "")
        aliases_raw = rec.get("aliases") or []
        alias_norms = [normalize_query(a) for a in aliases_raw if normalize_query(a)]
        section_norm = normalize_query(rec.get("section") or "")
        prepared.append(
            {
                "record": rec,
                "name_norm_prepared": name_norm,
                "aliases_norm_prepared": sorted(set(alias_norms)),
                "section_norm_prepared": section_norm,
            }
        )

    _PREPARED_CACHE = prepared
    return prepared


def _query_section_signals(query_norm: str) -> set[str]:
    signals: set[str] = set()
    if any(token in query_norm for token in ("جيني", "وراث", "dna", "nifty")):
        signals.add("genetic")
    if any(token in query_norm for token in ("ذاتي", "سيبو", "self", "منزلي")):
        signals.add("self")
    return signals


def _section_relevance_score(section_norm: str, query_signals: set[str]) -> float:
    if not query_signals or not section_norm:
        return 0.0
    boost = 0.0
    if "genetic" in query_signals and ("جيني" in section_norm or "وراث" in section_norm):
        boost += 0.06
    if "self" in query_signals and "ذاتي" in section_norm:
        boost += 0.06
    return boost


def _match_candidate(
    query_norm: str,
    name_norm: str,
    aliases_norm: list[str],
) -> Optional[dict[str, Any]]:
    if not query_norm or not name_norm:
        return None

    if query_norm == name_norm:
        return {"score": 1.0, "kind": "exact_name", "matched_len": len(name_norm)}

    for alias in aliases_norm:
        if query_norm == alias:
            return {"score": 0.95, "kind": "exact_alias", "matched_len": len(alias)}

    if query_norm in name_norm or name_norm in query_norm:
        matched = query_norm if query_norm in name_norm else name_norm
        score = 0.80 + min(len(matched), 60) / 300.0
        return {"score": min(score, 0.92), "kind": "contains_name", "matched_len": len(matched)}

    best_alias_len = -1
    for alias in aliases_norm:
        if query_norm in alias or alias in query_norm:
            matched = query_norm if query_norm in alias else alias
            best_alias_len = max(best_alias_len, len(matched))
    if best_alias_len > 0:
        score = 0.70 + min(best_alias_len, 60) / 400.0
        return {
            "score": min(score, 0.85),
            "kind": "contains_alias",
            "matched_len": best_alias_len,
        }

    # token overlap fallback for multi-word Arabic/English queries.
    q_tokens = [t for t in query_norm.split() if t]
    n_tokens = set(name_norm.split())
    if q_tokens and n_tokens:
        overlap = [t for t in q_tokens if t in n_tokens]
        if overlap:
            longest = max(len(t) for t in overlap)
            ratio = len(set(overlap)) / max(len(set(q_tokens)), 1)
            score = 0.60 + (0.18 * ratio) + min(longest, 12) / 200.0
            return {
                "score": min(score, 0.84),
                "kind": "token_overlap",
                "matched_len": longest,
            }
    return None


def _is_better_candidate(a: dict[str, Any], b: dict[str, Any]) -> bool:
    # True if candidate a is better than b.
    a_price = 1 if a["record"].get("price_value") is not None else 0
    b_price = 1 if b["record"].get("price_value") is not None else 0
    a_key = (
        a["score"],
        a["matched_len"],
        a_price,
        -int(a["record"].get("row", 10**9)),
    )
    b_key = (
        b["score"],
        b["matched_len"],
        b_price,
        -int(b["record"].get("row", 10**9)),
    )
    return a_key > b_key


def search_packages(query: str, top_k: int = 8) -> list[dict[str, Any]]:
    """Search package/test records deterministically."""
    query_norm = normalize_query(query)
    if not query_norm:
        return []

    signals = _query_section_signals(query_norm)
    candidates: list[dict[str, Any]] = []

    for prepared in _prepare_records():
        match = _match_candidate(
            query_norm=query_norm,
            name_norm=prepared["name_norm_prepared"],
            aliases_norm=prepared["aliases_norm_prepared"],
        )
        if not match:
            continue

        section_boost = _section_relevance_score(prepared["section_norm_prepared"], signals)
        score = min(1.05, match["score"] + section_boost)
        candidates.append(
            {
                "record": prepared["record"],
                "score": score,
                "matched_len": match["matched_len"],
                "match_kind": match["kind"],
            }
        )

    if not candidates:
        return []

    # Deduplicate by normalized name and keep the best candidate.
    best_by_name: dict[str, dict[str, Any]] = {}
    for cand in candidates:
        name_key = normalize_query(cand["record"].get("name_norm") or cand["record"].get("name_raw") or "")
        prev = best_by_name.get(name_key)
        if prev is None or _is_better_candidate(cand, prev):
            best_by_name[name_key] = cand

    deduped = list(best_by_name.values())
    deduped.sort(
        key=lambda c: (
            c["score"],
            c["matched_len"],
            1 if c["record"].get("price_value") is not None else 0,
            -int(c["record"].get("row", 10**9)),
        ),
        reverse=True,
    )

    return [c["record"] for c in deduped[: max(top_k, 0)]]


def match_single_package(query: str) -> Optional[dict[str, Any]]:
    """Return a single strong match or None."""
    matches = search_packages(query, top_k=3)
    if not matches:
        return None

    query_norm = normalize_query(query)
    top = matches[0]
    name_norm = normalize_query(top.get("name_norm") or top.get("name_raw") or "")
    alias_norms = [normalize_query(a) for a in (top.get("aliases") or [])]

    if query_norm == name_norm or query_norm in alias_norms:
        return top

    scored = _match_candidate(query_norm, name_norm, alias_norms)
    if scored and scored["score"] >= 0.83:
        return top
    return None


def format_package_list(records: list[dict[str, Any]], max_items: int = 6) -> str:
    items = records[: max(0, max_items)]
    lines = ["هذه الخيارات المتاحة:"]
    for i, rec in enumerate(items, start=1):
        lines.append(f"{i}) {rec.get('name_raw', '').strip()}")
    lines.append("اختر رقم الخيار المناسب لأرسل لك التفاصيل والسعر.")
    return "\n".join(lines)


def _split_text_units(text: str) -> list[str]:
    if not text:
        return []
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    units: list[str] = []
    for line in lines:
        parts = re.split(r"[.!؟]\s+|\.\n", line)
        for part in parts:
            p = part.strip(" -\u2022\t")
            if p:
                units.append(_WS_RE.sub(" ", p))
    return units


def _extract_detail_bullets(record: dict[str, Any], max_items: int = 4) -> list[str]:
    bullets: list[str] = []
    seen: set[str] = set()

    def add(text: Optional[str]) -> None:
        if not text:
            return
        cleaned = _WS_RE.sub(" ", str(text)).strip()
        if not cleaned:
            return
        key = normalize_query(cleaned)
        if not key or key in seen:
            return
        seen.add(key)
        bullets.append(cleaned)

    # Include explicit fields first if present.
    add(record.get("turnaround_text"))
    add(record.get("sample_type_text"))

    units = _split_text_units(record.get("description_raw") or "")
    keyword_units = [u for u in units if any(k in u for k in _DETAIL_KEYWORDS)]
    for u in keyword_units:
        if len(bullets) >= max_items:
            break
        add(u)

    if len(bullets) < max_items and not keyword_units:
        # Fallback to first 1-2 short sentences.
        for u in units[:2]:
            if len(bullets) >= max_items:
                break
            add(u)

    return bullets[:max_items]


def format_package_details(record: dict[str, Any]) -> str:
    name = (record.get("name_raw") or "").strip()
    price_raw = (record.get("price_raw") or "").strip()

    lines = [name]
    if price_raw:
        lines.append(f"السعر: {price_raw}")
    else:
        lines.append("السعر: غير متوفر حالياً")

    bullets = _extract_detail_bullets(record, max_items=4)
    if bullets:
        for b in bullets:
            lines.append(f"- {b}")

    return "\n".join(lines)
