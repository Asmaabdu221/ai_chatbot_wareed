"""
Packages semantic fallback service (RAG-lite over packages_kb.json only).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from app.services.embeddings_service import get_embedding, get_embeddings

logger = logging.getLogger(__name__)

PACKAGES_KB_PATH = Path(__file__).resolve().parents[1] / "data" / "packages_kb.json"

_KB_CACHE: Optional[list[dict[str, Any]]] = None
_DOC_EMBEDDINGS_CACHE: Optional[list[list[float]]] = None


def _norm(v: list[float]) -> float:
    return sum(x * x for x in v) ** 0.5


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    na = _norm(a)
    nb = _norm(b)
    if na == 0 or nb == 0:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (na * nb)


def load_packages_kb() -> list[dict[str, Any]]:
    global _KB_CACHE
    if _KB_CACHE is not None:
        return _KB_CACHE

    if not PACKAGES_KB_PATH.exists():
        logger.warning("packages_kb.json not found at %s", PACKAGES_KB_PATH)
        _KB_CACHE = []
        return _KB_CACHE

    try:
        raw = json.loads(PACKAGES_KB_PATH.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            logger.warning("packages_kb.json must be a list")
            _KB_CACHE = []
            return _KB_CACHE
        _KB_CACHE = [r for r in raw if isinstance(r, dict)]
    except Exception as exc:
        logger.warning("failed loading packages_kb.json: %s", exc)
        _KB_CACHE = []
    return _KB_CACHE


def _ensure_doc_embeddings() -> list[list[float]]:
    global _DOC_EMBEDDINGS_CACHE
    if _DOC_EMBEDDINGS_CACHE is not None:
        return _DOC_EMBEDDINGS_CACHE

    kb = load_packages_kb()
    if not kb:
        _DOC_EMBEDDINGS_CACHE = []
        return _DOC_EMBEDDINGS_CACHE

    texts = []
    for doc in kb:
        name = str(doc.get("name") or "").strip()
        section = str(doc.get("section") or "").strip()
        content = str(doc.get("content") or "").strip()
        texts.append("\n".join([p for p in [name, section, content] if p]))

    vectors = get_embeddings(texts) if texts else []
    if len(vectors) != len(texts):
        vectors = [[] for _ in texts]

    _DOC_EMBEDDINGS_CACHE = [v if isinstance(v, list) else [] for v in vectors]
    return _DOC_EMBEDDINGS_CACHE


def semantic_search_packages(query: str, top_k: int = 3) -> list[dict[str, Any]]:
    query = (query or "").strip()
    if not query:
        return []

    kb = load_packages_kb()
    if not kb:
        return []

    q_emb = get_embedding(query)
    if not q_emb:
        return []

    doc_embeddings = _ensure_doc_embeddings()
    if not doc_embeddings or len(doc_embeddings) != len(kb):
        return []

    scored: list[dict[str, Any]] = []
    for i, emb in enumerate(doc_embeddings):
        if not emb:
            continue
        score = _cosine_similarity(q_emb, emb)
        scored.append(
            {
                "id": kb[i].get("id"),
                "name": kb[i].get("name"),
                "section": kb[i].get("section"),
                "content": kb[i].get("content"),
                "score": float(score),
            }
        )

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[: max(top_k, 0)]
