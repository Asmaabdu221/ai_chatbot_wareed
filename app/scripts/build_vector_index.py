"""
Build (or rebuild) the ChromaDB vector index for Lab RAG v2.

Embeds one *trimmed* document per test (OpenAI text-embedding-3-small) and
stores it in the ``lab_tests_v2`` collection (cosine) with useful metadata.

Token-safe: documents are short (~<=250 tokens) and batched to stay well under
OpenAI's 300k-tokens-per-request limit. Embedding calls retry with backoff.
Idempotent: already-indexed test_ids are skipped (safe to resume after a crash).

Run:
    python -m app.scripts.build_vector_index            # incremental build
    python -m app.scripts.build_vector_index --dry-run  # validate, no API calls
    python -m app.scripts.build_vector_index --rebuild  # drop + re-index all

Requires: chromadb, openai (+ OPENAI_API_KEY). tiktoken is used for accurate
token counting when available, with a safe character-based fallback otherwise.
"""

from __future__ import annotations

import argparse
import math
import sys
import time

from app.data.lab_data_loader import LabDataLoader, COL_ID, COL_NAME_AR, COL_NAME_EN
from app.services.lab_retrieval_engine import CHROMA_DIR, COLLECTION_NAME

# Pricing: text-embedding-3-small = $0.02 per 1M tokens.
PRICE_PER_1M = 0.02
MAX_TOKENS_PER_BATCH = 200_000
EMBED_MODEL_DEFAULT = "text-embedding-3-small"


def _clean(v) -> str:
    s = str(v or "").strip()
    return "" if s.lower() in ("nan", "none") or s.startswith("NEEDS") else s


def build_test_document(row: dict) -> str:
    """Build a SHORT semantic document per test (only fields that aid search).

    Fields are individually trimmed and the whole document is hard-capped, so
    no single document can blow the embedding token budget.
    """
    name_en = _clean(row.get(COL_NAME_EN)) or _clean(row.get("اسم التحليل بالإنجليزية"))
    fields = [
        _clean(row.get(COL_NAME_AR, "")),       # Arabic name
        name_en,                                 # English name
        _clean(row.get("short_names", "")),      # nicknames/abbrevs
        _clean(row.get("فائدة التحليل", ""))[:100],   # clinical use (trimmed)
        _clean(row.get("who_needs_it", "")),
        _clean(row.get("best_for", "")),
        _clean(row.get("symptoms_aliases", ""))[:150],  # symptom phrasings (trimmed)
        _clean(row.get("clinical_category", "")),
    ]
    doc = " | ".join(f.strip()[:150] for f in fields if f.strip())
    return doc[:500]  # hard cap


def _token_counter():
    """Return a function counting tokens; uses tiktoken if available."""
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return lambda s: len(enc.encode(s))
    except Exception:
        # Conservative fallback for Arabic when tiktoken can't load (~2 chars/token).
        return lambda s: max(1, len(s) // 2)


def chunk_by_tokens(documents: list[str], ids: list, metadatas: list,
                    max_tokens_per_batch: int = MAX_TOKENS_PER_BATCH) -> list:
    """Split documents into batches that respect the per-request token limit."""
    count = _token_counter()
    batches = []
    cur_docs, cur_ids, cur_metas, cur_tokens = [], [], [], 0
    for doc, id_, meta in zip(documents, ids, metadatas):
        tk = count(doc)
        if cur_tokens + tk > max_tokens_per_batch and cur_docs:
            batches.append((cur_docs, cur_ids, cur_metas))
            cur_docs, cur_ids, cur_metas, cur_tokens = [], [], [], 0
        cur_docs.append(doc)
        cur_ids.append(id_)
        cur_metas.append(meta)
        cur_tokens += tk
    if cur_docs:
        batches.append((cur_docs, cur_ids, cur_metas))
    return batches


def embed_with_retry(client, texts: list[str], model: str, max_retries: int = 3) -> list:
    """Embed texts with exponential backoff (1s, 2s, 4s) on transient failures."""
    for attempt in range(max_retries):
        try:
            response = client.embeddings.create(model=model, input=texts)
            return [item.embedding for item in response.data]
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            wait = 2 ** attempt
            print(f"  Attempt {attempt + 1} failed: {e}. Retrying in {wait}s...", file=sys.stderr)
            time.sleep(wait)


def _collect_documents(loader: LabDataLoader):
    """Build (documents, ids, metadatas) from the master sheet (skips empty docs)."""
    master = loader.load_master()
    documents, ids, metadatas = [], [], []
    for _, r in master.iterrows():
        row = r.to_dict()
        doc = build_test_document(row)
        if not doc:
            continue
        price = str(row.get("السعر", "")).strip()
        documents.append(doc)
        ids.append(str(row[COL_ID]).strip())
        metadatas.append({
            "test_id": str(row[COL_ID]).strip(),
            "category": str(row.get("clinical_category", "")),
            "fasting": str(row.get("fasting_required", "")),
            "available": str(row.get("is_available", "")),
            "has_price": "1" if price and price not in ("NEEDS_PRICE", "NEEDS_REVIEW") else "0",
        })
    return documents, ids, metadatas


def build_index(max_tokens_per_batch: int = MAX_TOKENS_PER_BATCH,
                dry_run: bool = False, rebuild: bool = False) -> int:
    """Build the vector index. Returns the number of tests embedded this run."""
    from app.core.config import settings
    model = getattr(settings, "OPENAI_EMBEDDING_MODEL", EMBED_MODEL_DEFAULT)

    loader = LabDataLoader()
    documents, ids, metadatas = _collect_documents(loader)

    # ---- pre-flight report (cost + batching) ----
    count = _token_counter()
    doc_tokens = [count(d) for d in documents]
    total_tokens = sum(doc_tokens)
    batches = chunk_by_tokens(documents, ids, metadatas, max_tokens_per_batch)
    est_cost = total_tokens / 1_000_000 * PRICE_PER_1M
    print("=" * 56)
    print("Vector index build — pre-flight")
    print(f"  Total documents      : {len(documents)}")
    print(f"  Max tokens / document: {max(doc_tokens) if doc_tokens else 0}")
    print(f"  Avg tokens / document: {total_tokens // len(documents) if documents else 0}")
    print(f"  Total est. tokens    : {total_tokens:,}")
    print(f"  Estimated cost       : ${est_cost:.4f} (text-embedding-3-small @ ${PRICE_PER_1M}/1M)")
    print(f"  Batches (<= {max_tokens_per_batch:,} tok): {len(batches)}")
    print("=" * 56)

    # ---- dry run: validate only, no API / no chromadb ----
    if dry_run:
        print("DRY RUN — no API calls will be made\n")
        for doc, id_, tk in zip(documents, ids, doc_tokens):
            print(f"  {id_}: {tk} tokens | {doc[:80]}")
        print(f"\nTotal: {total_tokens:,} tokens across {len(documents)} docs")
        print(f"Would split into {math.ceil(total_tokens / max_tokens_per_batch)} "
              f"batch(es) (token-aware: {len(batches)})")
        return 0

    # ---- dependencies needed only for the actual write ----
    try:
        import chromadb
    except Exception:
        print("ERROR: chromadb is not installed. Run: pip install chromadb", file=sys.stderr)
        raise SystemExit(2)
    try:
        from openai import OpenAI
    except Exception:
        print("ERROR: openai is not installed. Run: pip install openai", file=sys.stderr)
        raise SystemExit(2)

    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    chroma = chromadb.PersistentClient(path=str(CHROMA_DIR))
    if rebuild:
        try:
            chroma.delete_collection(COLLECTION_NAME)
            print("Rebuild: dropped existing collection.")
        except Exception:
            pass
    collection = chroma.get_or_create_collection(name=COLLECTION_NAME, metadata={"hnsw:space": "cosine"})

    # ---- idempotency: skip test_ids already present ----
    try:
        existing_ids = set(collection.get(include=[]).get("ids", []))
    except Exception:
        existing_ids = set()
    triples = [(d, i, m) for d, i, m in zip(documents, ids, metadatas) if i not in existing_ids]
    if not triples:
        print(f"All {len(documents)} tests already indexed. Nothing to do.")
        return 0
    if existing_ids:
        print(f"Indexing {len(triples)} new tests ({len(existing_ids)} already exist)...")

    te_docs = [t[0] for t in triples]
    te_ids = [t[1] for t in triples]
    te_metas = [t[2] for t in triples]
    todo_batches = chunk_by_tokens(te_docs, te_ids, te_metas, max_tokens_per_batch)

    done = 0
    for bi, (b_docs, b_ids, b_metas) in enumerate(todo_batches, 1):
        try:
            embs = embed_with_retry(client, b_docs, model)
        except Exception as exc:
            print(f"ERROR: embedding failed on batch {bi} (check OPENAI_API_KEY / network): {exc}", file=sys.stderr)
            raise SystemExit(3)
        collection.add(documents=b_docs, ids=b_ids, metadatas=b_metas, embeddings=embs)
        done += len(b_docs)
        print(f"  batch {bi}/{len(todo_batches)} -> embedded {done}/{len(te_docs)}")

    print(f"Done. {done} tests embedded into '{COLLECTION_NAME}' at {CHROMA_DIR}")
    return done


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the Lab RAG v2 vector index.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate documents and batch plan without calling OpenAI.")
    parser.add_argument("--rebuild", action="store_true",
                        help="Drop the existing collection and re-index everything.")
    parser.add_argument("--max-tokens-per-batch", type=int, default=MAX_TOKENS_PER_BATCH)
    args = parser.parse_args()
    build_index(max_tokens_per_batch=args.max_tokens_per_batch,
                dry_run=args.dry_run, rebuild=args.rebuild)


if __name__ == "__main__":
    main()
