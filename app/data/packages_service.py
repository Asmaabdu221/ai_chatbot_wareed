"""
Deterministic runtime packages service.

Runtime-only source files:
- app/data/runtime/rag/packages_clean_v3.jsonl
- app/data/runtime/rag/packages_chunks_v2.jsonl
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

from app.core.runtime_paths import PACKAGES_CHUNKS_PATH, path_exists

RUNTIME_PACKAGES_CLEAN_PATH = Path("app/data/runtime/rag/packages_clean_v3.jsonl")

_PACKAGES_CACHE: Optional[list[dict[str, Any]]] = None
_PREPARED_CACHE: Optional[list[dict[str, Any]]] = None

_DIACRITICS_RE = re.compile(r"[\u064B-\u065F\u0670]")
_PUNCT_RE = re.compile(r"[^\w\s\u0600-\u06FF]")
_WS_RE = re.compile(r"\s+")


def _safe_str(v: Any) -> str:
    return "" if v is None else str(v)


def normalize_query(text: str) -> str:
    value = _safe_str(text).replace("\u00a0", " ")
    value = _DIACRITICS_RE.sub("", value)
    value = value.replace("ـ", "")
    value = value.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    value = value.replace("ى", "ي").replace("ة", "ه")
    value = value.replace("ئ", "ي").replace("ؤ", "و")
    value = value.lower()
    value = _PUNCT_RE.sub(" ", value)
    value = _WS_RE.sub(" ", value).strip()
    return value


def _iter_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            raw = (line or "").strip()
            if not raw:
                continue
            try:
                item = json.loads(raw)
            except Exception:
                continue
            if isinstance(item, dict):
                out.append(item)
    return out


def _build_aliases(name: str, tags: list[str], section: str) -> list[str]:
    aliases: set[str] = set()

    def add(v: str) -> None:
        t = _safe_str(v).strip()
        if t:
            aliases.add(t)

    add(name)
    add(section)
    for t in tags:
        add(t)

    base = re.sub(r"[()\[\]{}]", " ", name)
    add(base)
    for part in re.split(r"[-/|]", base):
        add(part)
    for token in normalize_query(name).split():
        if len(token) >= 3:
            add(token)

    return sorted({a for a in aliases if normalize_query(a)})


def _map_clean_record(rec: dict[str, Any], row_idx: int, desc_from_chunks: str = "") -> dict[str, Any]:
    name = _safe_str(rec.get("package_name")).strip()
    section = _safe_str(rec.get("main_category")).strip()
    desc = _safe_str(rec.get("description")).strip() or desc_from_chunks
    price_raw = _safe_str(rec.get("price_raw")).strip() or None
    tags = rec.get("tags") if isinstance(rec.get("tags"), list) else []
    tags = [_safe_str(t).strip() for t in tags if _safe_str(t).strip()]

    return {
        "id": _safe_str(rec.get("id")).strip() or f"pkg::{row_idx}",
        "row": row_idx,
        "section": section,
        "name_raw": name,
        "name_norm": normalize_query(name),
        "description_raw": desc,
        "price_raw": price_raw,
        "price_value": rec.get("price_number"),
        "aliases": _build_aliases(name=name, tags=tags, section=section),
        "tags": tags,
    }

def _chunk_descriptions_by_package() -> dict[str, str]:
    if not path_exists(PACKAGES_CHUNKS_PATH):
        return {}
    out: dict[str, str] = {}
    for item in _iter_jsonl(PACKAGES_CHUNKS_PATH):
        pkg_id = _safe_str(item.get("package_id") or item.get("id")).strip()
        text = _safe_str(item.get("text")).strip()
        if not pkg_id or not text:
            continue
        if pkg_id not in out:
            out[pkg_id] = text
    return out


def load_packages_index() -> list[dict[str, Any]]:
    """Runtime-first only. No fallback to legacy packages_index.json."""
    global _PACKAGES_CACHE
    if _PACKAGES_CACHE is not None:
        return _PACKAGES_CACHE

    if not path_exists(PACKAGES_CHUNKS_PATH) and not RUNTIME_PACKAGES_CLEAN_PATH.exists():
        _PACKAGES_CACHE = []
        return _PACKAGES_CACHE

    print("PATH=runtime_packages")

    chunk_desc = _chunk_descriptions_by_package()
    clean_rows = _iter_jsonl(RUNTIME_PACKAGES_CLEAN_PATH)

    records: list[dict[str, Any]] = []
    if clean_rows:
        for i, rec in enumerate(clean_rows, 1):
            pkg_id = _safe_str(rec.get("id")).strip()
            records.append(_map_clean_record(rec, i, chunk_desc.get(pkg_id, "")))
    else:
        seen: set[str] = set()
        for i, ch in enumerate(_iter_jsonl(PACKAGES_CHUNKS_PATH), 1):
            pkg_id = _safe_str(ch.get("package_id") or ch.get("id")).strip()
            if not pkg_id or pkg_id in seen:
                continue
            seen.add(pkg_id)
            rec = {
                "id": pkg_id,
                "package_name": _safe_str(ch.get("package_name")),
                "main_category": _safe_str(ch.get("main_category")),
                "description": _safe_str(ch.get("text")),
                "price_raw": _safe_str(ch.get("price_raw")),
                "price_number": ch.get("price_number"),
                "tags": ch.get("tags") if isinstance(ch.get("tags"), list) else [],
            }
            records.append(_map_clean_record(rec, i))

    _PACKAGES_CACHE = records
    return _PACKAGES_CACHE


def _prepare_records() -> list[dict[str, Any]]:
    global _PREPARED_CACHE
    if _PREPARED_CACHE is not None:
        return _PREPARED_CACHE

    prepared: list[dict[str, Any]] = []
    for rec in load_packages_index():
        aliases = rec.get("aliases") or []
        aliases_norm = sorted({normalize_query(a) for a in aliases if normalize_query(a)})
        prepared.append(
            {
                "record": rec,
                "name_norm_prepared": normalize_query(rec.get("name_raw") or rec.get("name_norm") or ""),
                "aliases_norm_prepared": aliases_norm,
            }
        )

    _PREPARED_CACHE = prepared
    return prepared


def _is_catalog_query(query_norm: str) -> bool:
    return any(t in query_norm for t in ("باقات", "باقه", "عروض", "العروض", "المتوفرة", "المتوفره"))


def _match_candidate(query_norm: str, name_norm: str, aliases_norm: list[str]) -> Optional[dict[str, Any]]:
    if not query_norm or not name_norm:
        return None

    if query_norm == name_norm:
        return {"score": 1.0, "kind": "exact_name", "matched_len": len(name_norm)}

    for alias in aliases_norm:
        if query_norm == alias:
            return {"score": 0.96, "kind": "exact_alias", "matched_len": len(alias)}

    if query_norm in name_norm or name_norm in query_norm:
        matched = query_norm if query_norm in name_norm else name_norm
        return {"score": 0.88, "kind": "contains_name", "matched_len": len(matched)}

    best_alias_len = -1
    for alias in aliases_norm:
        if query_norm in alias or alias in query_norm:
            matched = query_norm if query_norm in alias else alias
            best_alias_len = max(best_alias_len, len(matched))
    if best_alias_len > 0:
        return {"score": 0.82, "kind": "contains_alias", "matched_len": best_alias_len}

    q_tokens = set(query_norm.split())
    n_tokens = set(name_norm.split())
    if q_tokens and n_tokens:
        overlap = q_tokens & n_tokens
        if overlap:
            return {"score": 0.75, "kind": "token_overlap", "matched_len": max(len(t) for t in overlap)}

    return None

def _is_better_candidate(a: dict[str, Any], b: dict[str, Any]) -> bool:
    a_price = 1 if a["record"].get("price_value") is not None else 0
    b_price = 1 if b["record"].get("price_value") is not None else 0
    a_key = (a["score"], a["matched_len"], a_price, -int(a["record"].get("row", 10**9)))
    b_key = (b["score"], b["matched_len"], b_price, -int(b["record"].get("row", 10**9)))
    return a_key > b_key


def search_packages(query: str, top_k: int = 8) -> list[dict[str, Any]]:
    query_norm = normalize_query(query)
    if not query_norm:
        return []

    prepared = _prepare_records()
    if not prepared:
        print("PATH=runtime_packages no_match")
        return []

    candidates: list[dict[str, Any]] = []
    for row in prepared:
        match = _match_candidate(query_norm, row["name_norm_prepared"], row["aliases_norm_prepared"])
        if not match:
            continue
        candidates.append(
            {
                "record": row["record"],
                "score": match["score"],
                "matched_len": match["matched_len"],
            }
        )

    if not candidates and _is_catalog_query(query_norm):
        return [r["record"] for r in prepared[: max(top_k, 0)]]

    if not candidates:
        print("PATH=runtime_packages no_match")
        return []

    best_by_name: dict[str, dict[str, Any]] = {}
    for cand in candidates:
        key = normalize_query(cand["record"].get("name_norm") or cand["record"].get("name_raw") or "")
        prev = best_by_name.get(key)
        if prev is None or _is_better_candidate(cand, prev):
            best_by_name[key] = cand

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
    matches = search_packages(query, top_k=3)
    if not matches:
        return None

    query_norm = normalize_query(query)
    top = matches[0]
    name_norm = normalize_query(top.get("name_norm") or top.get("name_raw") or "")
    alias_norms = [normalize_query(a) for a in (top.get("aliases") or []) if normalize_query(a)]

    if query_norm == name_norm or query_norm in alias_norms:
        return top

    score = _match_candidate(query_norm, name_norm, alias_norms)
    if score and score["score"] >= 0.86:
        return top

    print("PATH=runtime_packages no_match")
    return None


def format_package_list(records: list[dict[str, Any]], max_items: int = 6) -> str:
    items = records[: max(0, max_items)]
    lines = ["هذه الخيارات المتاحة:"]
    for i, rec in enumerate(items, start=1):
        lines.append(f"{i}) {(_safe_str(rec.get('name_raw'))).strip()}")
    lines.append("اختر رقم الخيار المناسب لأرسل لك التفاصيل والسعر.")
    return "\n".join(lines)


def _split_text_units(text: str) -> list[str]:
    if not text:
        return []
    lines = [line.strip() for line in _safe_str(text).splitlines() if line.strip()]
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
        cleaned = _WS_RE.sub(" ", _safe_str(text)).strip()
        if not cleaned:
            return
        key = normalize_query(cleaned)
        if not key or key in seen:
            return
        seen.add(key)
        bullets.append(cleaned)

    units = _split_text_units(record.get("description_raw") or "")
    for u in units:
        if len(bullets) >= max_items:
            break
        add(u)

    return bullets[:max_items]


def format_package_details(record: dict[str, Any]) -> str:
    name = _safe_str(record.get("name_raw")).strip()
    price_raw = _safe_str(record.get("price_raw")).strip()

    lines = [name or "الباقة"]
    if price_raw:
        lines.append(f"السعر: {price_raw}")
    else:
        lines.append("السعر: غير متوفر حالياً")

    bullets = _extract_detail_bullets(record, max_items=4)
    for b in bullets:
        lines.append(f"- {b}")

    return "\n".join(lines)
