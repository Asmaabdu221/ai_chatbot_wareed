"""
Runtime branch lookup service from local branches_index.json.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Dict

BRANCHES_INDEX_PATH = Path(__file__).resolve().parent / "branches_index.json"

_CACHE: List[Dict] | None = None


def _normalize(text: str) -> str:
    value = (text or "").strip().lower()
    if not value:
        return ""
    value = re.sub(r"[\u064B-\u065F\u0670]", "", value)
    value = value.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    value = value.replace("ى", "ي").replace("ؤ", "و").replace("ئ", "ي")
    value = re.sub(r"[^\w\s\u0600-\u06FF]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def load_branches_index() -> List[Dict]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    if not BRANCHES_INDEX_PATH.exists():
        _CACHE = []
        return _CACHE
    with BRANCHES_INDEX_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)
    _CACHE = data if isinstance(data, list) else []
    return _CACHE


def get_available_cities() -> List[str]:
    items = load_branches_index()
    seen = set()
    out: List[str] = []
    for row in items:
        city = (row.get("group") or "").strip()
        if city and city not in seen:
            seen.add(city)
            out.append(city)
    return out


def find_branches_by_city(city_name: str) -> List[Dict]:
    query = _normalize(city_name)
    if not query:
        return []
    rows = load_branches_index()
    out: List[Dict] = []
    for row in rows:
        group = _normalize(row.get("group", ""))
        name = _normalize(row.get("branch_name", ""))
        if query in group or group in query or query in name:
            out.append(row)
    return out


def find_branches_by_keyword(keyword: str) -> List[Dict]:
    query = _normalize(keyword)
    if not query:
        return []
    rows = load_branches_index()
    out: List[Dict] = []
    for row in rows:
        group = _normalize(row.get("group", ""))
        name = _normalize(row.get("branch_name", ""))
        if query in name or query in group:
            out.append(row)
    return out

