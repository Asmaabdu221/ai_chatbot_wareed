"""Semantic search for packages domain using local embeddings + Chroma."""

from __future__ import annotations

import hashlib
import json
import logging
import gc
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.runtime.semantic_model_pool import get_shared_sentence_transformer
from app.services.runtime.unified_normalizer import get_wareed_normalizer

logger = logging.getLogger(__name__)

CHROMA_COLLECTION_NAME = "wareed_packages"
CHROMA_PERSIST_PATH = Path("app/data/runtime/chroma/packages")
DEFAULT_EMBED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

_NORMALIZER = get_wareed_normalizer()


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _norm(value: Any) -> str:
    return _NORMALIZER.normalize(_safe_str(value))


def _build_package_document(record: dict[str, Any]) -> str:
    package_name = _safe_str(record.get("package_name"))
    category = _safe_str(record.get("main_category"))
    short_desc = _safe_str(record.get("description_short"))
    full_desc = _safe_str(record.get("description_full"))
    best_for = [_safe_str(v) for v in _safe_list(record.get("best_for")) if _safe_str(v)]
    aliases = [_safe_str(v) for v in _safe_list(record.get("aliases")) if _safe_str(v)]
    tests_included = [_safe_str(v) for v in _safe_list(record.get("tests_included")) if _safe_str(v)]

    return "\n".join(
        [
            f"name: {package_name}",
            f"category: {category}",
            f"aliases: {' | '.join(aliases)}",
            f"best_for: {' | '.join(best_for)}",
            f"tests_included: {' | '.join(tests_included)}",
            f"description: {(short_desc + ' ' + full_desc).strip()[:500]}",
        ]
    )


def _records_fingerprint(records: list[dict[str, Any]]) -> str:
    payload = [
        {
            "id": _safe_str(r.get("id")),
            "package_name": _safe_str(r.get("package_name")),
            "category": _safe_str(r.get("main_category")),
            "description_short": _safe_str(r.get("description_short"))[:180],
            "description_full": _safe_str(r.get("description_full"))[:180],
            "aliases": [_safe_str(v) for v in _safe_list(r.get("aliases"))],
            "best_for": [_safe_str(v) for v in _safe_list(r.get("best_for"))],
        }
        for r in records
    ]
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


@dataclass
class PackageSemanticCandidate:
    record: dict[str, Any]
    distance: float
    score: float


class PackagesSemanticSearch:
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
        try:
            import chromadb  # type: ignore
        except Exception as exc:
            self._available = False
            self._reason = f"deps_missing:{exc.__class__.__name__}"
            logger.info("packages_semantic_search disabled | reason=%s", self._reason)
            return

        try:
            CHROMA_PERSIST_PATH.mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(path=str(CHROMA_PERSIST_PATH))
            self._collection = client.get_or_create_collection(
                name=CHROMA_COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
            )
            self._model = get_shared_sentence_transformer(DEFAULT_EMBED_MODEL)
            self._available = True
            self._reason = ""
        except Exception as exc:
            self._available = False
            self._reason = f"init_failed:{exc.__class__.__name__}"
            logger.warning("packages_semantic_search init failed | reason=%s", self._reason)

    def build_or_refresh(self, records: list[dict[str, Any]]) -> None:
        self.initialize()
        if not self._available:
            return
        assert self._collection is not None
        assert self._model is not None

        clean_records = [r for r in records if isinstance(r, dict) and _safe_str(r.get("id"))]
        if not clean_records:
            return

        fingerprint = _records_fingerprint(clean_records)
        count = int(self._collection.count() or 0)
        expected = len(clean_records)
        try:
            meta = self._collection.metadata or {}
            stored_fp = _safe_str(meta.get("packages_fingerprint"))
        except Exception:
            stored_fp = ""

        if count == expected and stored_fp == fingerprint:
            return

        ids: list[str] = []
        docs: list[str] = []
        metas: list[dict[str, Any]] = []
        for record in clean_records:
            rid = _safe_str(record.get("id"))
            ids.append(rid)
            docs.append(_build_package_document(record))
            metas.append(
                {
                    "package_id": rid,
                    "package_name": _safe_str(record.get("package_name")),
                    "category": _safe_str(record.get("main_category")),
                    "package_name_norm": _norm(record.get("package_name")),
                    "category_norm": _norm(record.get("main_category")),
                }
            )

        try:
            embeddings = self._model.encode(docs, normalize_embeddings=True).tolist()
            self._collection.delete(where={})
            self._collection.add(ids=ids, documents=docs, metadatas=metas, embeddings=embeddings)
            self._collection.modify(metadata={"hnsw:space": "cosine", "packages_fingerprint": fingerprint})
        finally:
            gc.collect()

    def query(
        self,
        text: str,
        records_by_id: dict[str, dict[str, Any]],
        *,
        top_k: int = 3,
    ) -> list[PackageSemanticCandidate]:
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

        out: list[PackageSemanticCandidate] = []
        ids = (raw.get("ids") or [[]])[0]
        distances = (raw.get("distances") or [[]])[0]
        for idx, package_id in enumerate(ids):
            key = _safe_str(package_id)
            record = records_by_id.get(key)
            if not record:
                continue
            distance = float(distances[idx]) if idx < len(distances) else 1.0
            score = 1.0 / (1.0 + max(0.0, distance))
            out.append(PackageSemanticCandidate(record=record, distance=distance, score=score))

        out.sort(key=lambda item: item.score, reverse=True)
        return out


_PACKAGES_SEMANTIC_SINGLETON: PackagesSemanticSearch | None = None


def get_packages_semantic_search() -> PackagesSemanticSearch:
    global _PACKAGES_SEMANTIC_SINGLETON
    if _PACKAGES_SEMANTIC_SINGLETON is None:
        _PACKAGES_SEMANTIC_SINGLETON = PackagesSemanticSearch()
    return _PACKAGES_SEMANTIC_SINGLETON


def search_packages(query: str, records: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    """Return ranked semantic candidates for packages (best-first)."""
    service = get_packages_semantic_search()
    service.build_or_refresh(records)
    if not service.available:
        return []
    by_id = {_safe_str(r.get("id")): r for r in records if isinstance(r, dict)}
    ranked = service.query(query, by_id, top_k=limit)
    return [
        {
            "record": item.record,
            "score": float(item.score),
            "distance": float(item.distance),
            "method": "packages_semantic_chroma",
        }
        for item in ranked
    ]
