"""
Runtime packages semantic fallback service (lexical/fuzzy over runtime chunks).
"""

from __future__ import annotations

import json
import logging
import re
from difflib import SequenceMatcher
from typing import Any, Optional

from app.core.runtime_paths import PACKAGES_CHUNKS_PATH, path_exists

logger = logging.getLogger(__name__)

_KB_CACHE: Optional[list[dict[str, Any]]] = None

_DIACRITICS_RE = re.compile(r"[\u064B-\u065F\u0670]")
_PUNCT_RE = re.compile(r"[^\w\s\u0600-\u06FF]")
_WS_RE = re.compile(r"\s+")


def _norm_text(text: str) -> str:
    value = (text or "").strip().lower()
    if not value:
        return ""
    value = _DIACRITICS_RE.sub("", value)
    value = value.replace("ـ", "")
    value = value.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    value = value.replace("ى", "ي").replace("ة", "ه")
    value = _PUNCT_RE.sub(" ", value)
    value = _WS_RE.sub(" ", value).strip()
    return value


def _iter_runtime_chunks() -> list[dict[str, Any]]:
    if not path_exists(PACKAGES_CHUNKS_PATH):
        return []
    rows: list[dict[str, Any]] = []
    with PACKAGES_CHUNKS_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            raw = (line or "").strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except Exception:
                continue
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


def load_packages_kb() -> list[dict[str, Any]]:
    global _KB_CACHE
    if _KB_CACHE is not None:
        return _KB_CACHE

    rows = _iter_runtime_chunks()
    if not rows:
        _KB_CACHE = []
        return _KB_CACHE

    print("PATH=runtime_packages")
    _KB_CACHE = rows
    return _KB_CACHE


def _score(query_norm: str, row: dict[str, Any]) -> float:
    text = str(row.get("text") or "").strip()
    package_name = str(row.get("package_name") or "").strip()
    section = str(row.get("main_category") or "").strip()
    tags = row.get("tags") if isinstance(row.get("tags"), list) else []

    haystack = " ".join([p for p in [package_name, section, text, " ".join(str(t) for t in tags)] if p])
    hay_norm = _norm_text(haystack)
    if not hay_norm:
        return 0.0

    if query_norm == _norm_text(package_name):
        return 1.0
    if query_norm in hay_norm:
        return 0.92
    if hay_norm in query_norm and len(hay_norm) >= 6:
        return 0.86

    q_tokens = set(query_norm.split())
    h_tokens = set(hay_norm.split())
    if q_tokens and h_tokens:
        overlap = len(q_tokens & h_tokens) / max(len(q_tokens), 1)
        if overlap >= 0.5:
            return 0.75 + min(0.15, overlap * 0.2)

    sim = SequenceMatcher(None, query_norm, hay_norm[: max(len(query_norm) * 4, len(query_norm))]).ratio()
    if sim >= 0.8:
        return 0.65 + min(0.2, sim * 0.25)

    return 0.0


def semantic_search_packages(query: str, top_k: int = 3) -> list[dict[str, Any]]:
    query_norm = _norm_text(query)
    if not query_norm:
        return []

    kb = load_packages_kb()
    if not kb:
        print("PATH=runtime_packages no_match")
        return []

    scored: list[dict[str, Any]] = []
    for row in kb:
        s = _score(query_norm, row)
        if s <= 0:
            continue
        scored.append(
            {
                "id": row.get("id") or row.get("package_id"),
                "name": row.get("package_name"),
                "section": row.get("main_category"),
                "content": row.get("text"),
                "score": float(s),
            }
        )

    if not scored:
        print("PATH=runtime_packages no_match")
        return []

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[: max(top_k, 0)]
