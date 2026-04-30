"""Build Chroma semantic index for tests domain.

Usage:
    python -m app.data.build_tests_semantic_index
"""

from __future__ import annotations

import gc
import json
import logging
from pathlib import Path
from typing import Any

import chromadb  # type: ignore

from app.services.runtime.semantic_model_pool import get_shared_sentence_transformer
from app.services.runtime.tests_semantic_search import (
    CHROMA_COLLECTION_NAME,
    CHROMA_PERSIST_PATH,
    DEFAULT_EMBED_MODEL,
)
from app.services.runtime.unified_normalizer import get_wareed_normalizer

logger = logging.getLogger(__name__)

TESTS_JSONL_PATH = Path("app/data/runtime/rag/tests_clean.jsonl")
_NORMALIZER = get_wareed_normalizer()


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _as_list_of_str(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_safe_str(v) for v in value if _safe_str(v)]
    text = _safe_str(value)
    if not text:
        return []
    return [part.strip() for part in text.split(",") if part.strip()]


def load_tests_records() -> list[dict[str, Any]]:
    if not TESTS_JSONL_PATH.exists():
        logger.error("tests_clean.jsonl not found at %s", TESTS_JSONL_PATH)
        return []

    rows: list[dict[str, Any]] = []
    with TESTS_JSONL_PATH.open("r", encoding="utf-8") as f:
        for raw_line in f:
            line = _safe_str(raw_line)
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue

            test_name_ar = _safe_str(obj.get("test_name_ar"))
            title = _safe_str(obj.get("title"))
            h1 = _safe_str(obj.get("h1"))
            if not (test_name_ar or title or h1):
                continue

            tags = _as_list_of_str(obj.get("tags"))
            code_tokens = _as_list_of_str(obj.get("code_tokens"))
            item = dict(obj)
            item["id"] = _safe_str(obj.get("id"))
            item["test_name_ar"] = test_name_ar
            item["title"] = title
            item["h1"] = h1
            item["tags"] = tags
            item["code_tokens"] = code_tokens
            item["summary_ar"] = _safe_str(obj.get("summary_ar"))
            item["test_name_norm"] = _NORMALIZER.normalize(test_name_ar)
            item["title_norm"] = _NORMALIZER.normalize(title)
            item["h1_norm"] = _NORMALIZER.normalize(h1)
            item["is_active"] = bool(obj.get("is_active", True))
            rows.append(item)
    return rows


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s - %(message)s")
    records = load_tests_records()
    if not records:
        logger.error("No test records loaded. Aborting.")
        return 1

    active_records = [r for r in records if bool(r.get("is_active", True))]
    if active_records:
        records = active_records

    CHROMA_PERSIST_PATH.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_PERSIST_PATH))
    collection = client.get_or_create_collection(
        name=CHROMA_COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )

    from app.services.runtime.tests_semantic_search import _records_fingerprint, _build_test_document, _norm, _safe_str

    fingerprint = _records_fingerprint(records)
    existing_count = int(collection.count() or 0)
    existing_fp = _safe_str((collection.metadata or {}).get("tests_fingerprint"))
    if existing_count == len(records) and existing_fp == fingerprint:
        logger.info("Tests semantic index already up-to-date. Skipping rebuild.")
        return 0

    logger.info("Background semantic indexing started...")
    model = get_shared_sentence_transformer(DEFAULT_EMBED_MODEL)
    collection.delete(where={})

    batch_size = 50
    for i in range(0, len(records), batch_size):
        batch = records[i : i + batch_size]
        ids = [_safe_str(r.get("id")) for r in batch]
        docs = [_build_test_document(r) for r in batch]
        metas = [
            {
                "test_id": _safe_str(r.get("id")),
                "test_name_ar": _safe_str(r.get("test_name_ar")),
                "title": _safe_str(r.get("title")),
                "test_name_norm": _norm(r.get("test_name_ar")),
                "title_norm": _norm(r.get("title")),
                "h1_norm": _norm(r.get("h1")),
            }
            for r in batch
        ]
        embeddings = model.encode(docs, normalize_embeddings=True).tolist()
        collection.add(ids=ids, documents=docs, metadatas=metas, embeddings=embeddings)
        del embeddings, docs, metas, ids, batch
        gc.collect()

    collection.modify(metadata={"hnsw:space": "cosine", "tests_fingerprint": fingerprint})

    logger.info("Tests semantic index is ready | records=%d", len(records))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
