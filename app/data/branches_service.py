"""
Runtime branch lookup service from runtime RAG artifacts.
"""

from __future__ import annotations

import json
import re
from typing import Dict, List

from app.core.runtime_paths import BRANCHES_CHUNKS_PATH, path_exists

_CACHE: List[Dict] | None = None


def _normalize(text: str) -> str:
    value = (text or "").strip().lower()
    if not value:
        return ""
    value = re.sub(r"[\u064B-\u065F\u0670\u0640]", "", value)
    value = value.replace("؟", " ").replace("،", " ").replace("؛", " ")
    value = value.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    value = value.replace("ى", "ي").replace("ؤ", "و").replace("ئ", "ي").replace("ة", "ه")
    value = re.sub(r"[^\w\s\u0600-\u06FF]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def load_runtime_branches() -> List[Dict]:
    """Read runtime branches chunks JSONL and return chunk records."""
    if not path_exists(BRANCHES_CHUNKS_PATH):
        return []

    records: List[Dict] = []
    with BRANCHES_CHUNKS_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            raw = (line or "").strip()
            if not raw:
                continue
            try:
                item = json.loads(raw)
            except Exception:
                continue
            if isinstance(item, dict):
                records.append(item)
    return records


def _as_legacy_row(chunk: Dict) -> Dict:
    metadata = chunk.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}
    branch_name = (metadata.get("branch_name") or "").strip()
    section = (metadata.get("section") or "").strip()
    return {
        "id": chunk.get("id"),
        "text": chunk.get("text") or "",
        "metadata": metadata,
        "branch_name": branch_name,
        "group": section,
        "section": metadata.get("section"),
        "hours": metadata.get("hours"),
        "map_url": metadata.get("map_url"),
        "contact_phone": metadata.get("contact_phone"),
    }


def load_branches_index() -> List[Dict]:
    """Public API kept for compatibility; now backed by runtime branches chunks only."""
    global _CACHE
    if _CACHE is not None:
        return _CACHE

    chunks = load_runtime_branches()
    if not chunks:
        _CACHE = []
        return _CACHE

    print("PATH=runtime_branches")
    _CACHE = [_as_legacy_row(chunk) for chunk in chunks]
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


def _row_match(row: Dict, query: str) -> bool:
    metadata = row.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}

    section = _normalize(metadata.get("section") or row.get("group") or "")
    branch_name = _normalize(metadata.get("branch_name") or row.get("branch_name") or "")
    text = _normalize(row.get("text") or "")

    if query in branch_name or branch_name in query:
        return True
    if query in section or section in query:
        return True
    if query in text:
        return True

    stop_words = {
        "وين",
        "اين",
        "اقرب",
        "أقرب",
        "فرع",
        "فروع",
        "ما",
        "هي",
        "في",
        "بال",
        "ب",
        "من",
        "عن",
    }
    tokens: List[str] = []
    for token in query.split():
        t = token.strip()
        if not t:
            continue
        tokens.append(t)
        if t.startswith("بال") and len(t) > 3:
            tokens.append(t[2:])
        if t.startswith("ال") and len(t) > 3:
            tokens.append(t[2:])
        if t.startswith("ب") and len(t) > 2:
            tokens.append(t[1:])

    uniq_tokens = []
    seen = set()
    for token in tokens:
        if len(token) < 2 or token in stop_words:
            continue
        if token in seen:
            continue
        seen.add(token)
        uniq_tokens.append(token)

    for token in uniq_tokens:
        if token in branch_name or token in section or token in text:
            return True
    return False


def find_branches_by_city(city_name: str) -> List[Dict]:
    query = _normalize(city_name)
    if not query:
        return []

    rows = load_branches_index()
    out = [row for row in rows if _row_match(row, query)]
    if not out:
        print("PATH=runtime_branches no_match")
    return out


def find_branches_by_keyword(keyword: str) -> List[Dict]:
    query = _normalize(keyword)
    if not query:
        return []

    rows = load_branches_index()
    out = [row for row in rows if _row_match(row, query)]
    if not out:
        print("PATH=runtime_branches no_match")
    return out
