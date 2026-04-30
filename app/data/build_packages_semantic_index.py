"""Build Chroma semantic index for packages domain.

Usage:
    python -m app.data.build_packages_semantic_index
"""

from __future__ import annotations

import gc
import logging

import chromadb  # type: ignore

from app.services.runtime.packages_resolver import load_packages_records
from app.services.runtime.packages_semantic_search import (
    CHROMA_COLLECTION_NAME,
    CHROMA_PERSIST_PATH,
    DEFAULT_EMBED_MODEL,
)
from app.services.runtime.semantic_model_pool import get_shared_sentence_transformer

logger = logging.getLogger(__name__)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s - %(message)s")
    records = load_packages_records()
    if not records:
        logger.error("No package records loaded. Aborting.")
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

    from app.services.runtime.packages_semantic_search import (
        _records_fingerprint,
        _build_package_document,
        _norm,
        _safe_str,
    )

    fingerprint = _records_fingerprint(records)
    existing_count = int(collection.count() or 0)
    existing_fp = _safe_str((collection.metadata or {}).get("packages_fingerprint"))
    if existing_count == len(records) and existing_fp == fingerprint:
        logger.info("Packages semantic index already up-to-date. Skipping rebuild.")
        return 0

    logger.info("Background semantic indexing started...")
    model = get_shared_sentence_transformer(DEFAULT_EMBED_MODEL)
    collection.delete(where={})

    batch_size = 50
    for i in range(0, len(records), batch_size):
        batch = records[i : i + batch_size]
        ids = [_safe_str(r.get("id")) for r in batch]
        docs = [_build_package_document(r) for r in batch]
        metas = [
            {
                "package_id": _safe_str(r.get("id")),
                "package_name": _safe_str(r.get("package_name")),
                "category": _safe_str(r.get("main_category")),
                "package_name_norm": _norm(r.get("package_name")),
                "category_norm": _norm(r.get("main_category")),
            }
            for r in batch
        ]
        embeddings = model.encode(docs, normalize_embeddings=True).tolist()
        collection.add(ids=ids, documents=docs, metadatas=metas, embeddings=embeddings)
        del embeddings, docs, metas, ids, batch
        gc.collect()

    collection.modify(metadata={"hnsw:space": "cosine", "packages_fingerprint": fingerprint})

    logger.info("Packages semantic index is ready | records=%d", len(records))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
