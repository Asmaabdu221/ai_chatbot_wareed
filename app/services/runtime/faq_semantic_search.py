"""In-domain FAQ semantic search using local embeddings + Chroma.

Design constraints:
- FAQ-only usage (no top-level routing decisions here).
- Fully optional: if dependencies are missing, callers must fall back safely.
- No OpenAI embeddings.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.runtime.faq_canonicalizer import FAQ_CANONICAL_RULES

logger = logging.getLogger(__name__)

CHROMA_COLLECTION_NAME = "wareed_faq"
CHROMA_PERSIST_PATH = Path("app/data/runtime/chroma/faq")
DEFAULT_EMBED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _normalize_alias_values(values: Any) -> list[str]:
    out: list[str] = []
    for item in _safe_list(values):
        text = _safe_str(item)
        if text:
            out.append(text)
    return out


def _faq_aliases_from_rules(faq_id: str) -> list[str]:
    target = _safe_str(faq_id)
    if not target:
        return []
    for rule in FAQ_CANONICAL_RULES:
        if _safe_str(getattr(rule, "faq_id", "")) == target:
            phrases = getattr(rule, "trigger_phrases", ()) or ()
            return [text for text in (_safe_str(p) for p in phrases) if text]
    return []


def _build_faq_document(record: dict[str, Any]) -> str:
    question = _safe_str(record.get("question"))
    q_norm = _safe_str(record.get("q_norm"))
    answer = _safe_str(record.get("answer"))
    summary = answer[:320]
    faq_id = _safe_str(record.get("id"))

    aliases: list[str] = []
    aliases.extend(_normalize_alias_values(record.get("aliases")))
    aliases.extend(_normalize_alias_values(record.get("alias")))
    aliases.extend(_normalize_alias_values(record.get("variants")))
    aliases.extend(_faq_aliases_from_rules(faq_id))

    dedup: list[str] = []
    seen: set[str] = set()
    for item in [question, q_norm, *aliases]:
        key = _safe_str(item)
        if not key or key in seen:
            continue
        seen.add(key)
        dedup.append(key)

    alias_blob = " | ".join(dedup[2:]) if len(dedup) > 2 else ""
    parts = [
        f"question: {question}",
        f"normalized_question: {q_norm}",
        f"aliases: {alias_blob}",
        f"answer_summary: {summary}",
    ]
    return "\n".join(parts)


def _records_fingerprint(records: list[dict[str, Any]]) -> str:
    payload = [
        {
            "id": _safe_str(r.get("id")),
            "q": _safe_str(r.get("question")),
            "qn": _safe_str(r.get("q_norm")),
            "a": _safe_str(r.get("answer"))[:180],
        }
        for r in records
    ]
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


@dataclass
class FAQSemanticCandidate:
    record: dict[str, Any]
    distance: float
    score: float


class FAQSemanticSearch:
    """Local semantic search index for FAQ records."""

    def __init__(self) -> None:
        self._available = False
        self._reason = "uninitialized"
        self._collection = None
        self._model = None
        self._initialized = False

    @property
    def available(self) -> bool:
        return self._available

    @property
    def unavailable_reason(self) -> str:
        return self._reason

    def initialize(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        from app.services.runtime.semantic_model_pool import lab_rag_v2_enabled
        if lab_rag_v2_enabled():
            self._available = False
            self._reason = "disabled_for_lab_rag_v2"
            logger.info("faq_semantic_search disabled | reason=%s", self._reason)
            return
        try:
            import chromadb  # type: ignore
            from sentence_transformers import SentenceTransformer  # type: ignore
        except Exception as exc:
            self._available = False
            self._reason = f"deps_missing:{exc.__class__.__name__}"
            logger.info("faq_semantic_search disabled | reason=%s", self._reason)
            return

        try:
            CHROMA_PERSIST_PATH.mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(path=str(CHROMA_PERSIST_PATH))
            self._collection = client.get_or_create_collection(
                name=CHROMA_COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
            )
            self._model = SentenceTransformer(DEFAULT_EMBED_MODEL)
            self._available = True
            self._reason = ""
        except Exception as exc:
            self._available = False
            self._reason = f"init_failed:{exc.__class__.__name__}"
            logger.warning("faq_semantic_search init failed | reason=%s", self._reason)

    def build_or_refresh(self, faq_records: list[dict[str, Any]]) -> None:
        self.initialize()
        if not self._available:
            return
        assert self._collection is not None
        assert self._model is not None

        records = [r for r in faq_records if isinstance(r, dict) and _safe_str(r.get("id"))]
        if not records:
            return

        fingerprint = _records_fingerprint(records)
        count = int(self._collection.count() or 0)
        expected = len(records)
        try:
            meta = self._collection.metadata or {}
            stored_fp = _safe_str(meta.get("faq_fingerprint"))
        except Exception:
            stored_fp = ""

        if count == expected and stored_fp == fingerprint:
            return

        ids: list[str] = []
        docs: list[str] = []
        metas: list[dict[str, Any]] = []
        for record in records:
            faq_id = _safe_str(record.get("id"))
            ids.append(faq_id)
            docs.append(_build_faq_document(record))
            metas.append({"faq_id": faq_id, "question": _safe_str(record.get("question"))})

        embeddings = self._model.encode(docs, normalize_embeddings=True).tolist()
        self._collection.delete(where={})  # full refresh for deterministic consistency
        self._collection.add(ids=ids, documents=docs, metadatas=metas, embeddings=embeddings)
        self._collection.modify(metadata={"hnsw:space": "cosine", "faq_fingerprint": fingerprint})

    def query(
        self,
        text: str,
        faq_records_by_id: dict[str, dict[str, Any]],
        *,
        top_k: int = 5,
    ) -> list[FAQSemanticCandidate]:
        self.initialize()
        if not self._available:
            return []
        assert self._collection is not None
        assert self._model is not None

        query_text = _safe_str(text)
        if not query_text:
            return []

        query_embedding = self._model.encode([query_text], normalize_embeddings=True).tolist()
        raw = self._collection.query(
            query_embeddings=query_embedding,
            n_results=max(1, int(top_k)),
            include=["metadatas", "distances"],
        )

        out: list[FAQSemanticCandidate] = []
        ids = (raw.get("ids") or [[]])[0]
        distances = (raw.get("distances") or [[]])[0]
        for idx, faq_id in enumerate(ids):
            key = _safe_str(faq_id)
            record = faq_records_by_id.get(key)
            if not record:
                continue
            distance = float(distances[idx]) if idx < len(distances) else 1.0
            score = 1.0 / (1.0 + max(0.0, distance))
            out.append(FAQSemanticCandidate(record=record, distance=distance, score=score))

        out.sort(key=lambda item: item.score, reverse=True)
        return out


_FAQ_SEMANTIC_SINGLETON: FAQSemanticSearch | None = None


def get_faq_semantic_search() -> FAQSemanticSearch:
    global _FAQ_SEMANTIC_SINGLETON
    if _FAQ_SEMANTIC_SINGLETON is None:
        _FAQ_SEMANTIC_SINGLETON = FAQSemanticSearch()
    return _FAQ_SEMANTIC_SINGLETON


def find_best_faq_semantic_match(
    user_text: str,
    faq_records: list[dict[str, Any]],
    *,
    min_score: float = 0.62,
    min_margin: float = 0.02,
    top_k: int = 5,
) -> dict[str, Any] | None:
    """Return best semantic FAQ match, or None when unavailable/low-confidence."""
    service = get_faq_semantic_search()
    service.build_or_refresh(faq_records)
    if not service.available:
        return None

    by_id = {_safe_str(r.get("id")): r for r in faq_records if isinstance(r, dict)}
    ranked = service.query(user_text, by_id, top_k=top_k)
    if not ranked:
        return None

    best = ranked[0]
    second_score = ranked[1].score if len(ranked) > 1 else 0.0
    margin = float(best.score - second_score)
    if best.score < float(min_score):
        return None
    if len(ranked) > 1 and margin < float(min_margin):
        return None

    return {
        "record": best.record,
        "score": float(best.score),
        "distance": float(best.distance),
        "margin": margin,
        "matched_text": _safe_str(best.record.get("q_norm")) or _safe_str(best.record.get("question")),
        "method": "faq_semantic_chroma",
        "top_k": int(top_k),
    }

