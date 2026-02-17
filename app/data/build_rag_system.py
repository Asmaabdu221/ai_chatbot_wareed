"""
Build RAG System - Single Source: analysis_file.xlsx
====================================================
1. Load analysis_file.xlsx
2. Match prices from old file (knowledge_base_with_faq.json)
3. Save rag_knowledge_base.json
4. Generate embeddings (text-embedding-3-small or text-embedding-3-large)
5. Save rag_embeddings.json
6. Delete old indexes/embeddings (embeddings_cache.json)

Usage (from project root):
  python -m app.data.build_rag_system
"""

import io
import json
import logging
import os
import sys

# Fix Windows console encoding
if hasattr(sys.stdout, 'buffer') and sys.stdout.encoding and 'utf' not in (sys.stdout.encoding or '').lower():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Ensure app is on path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = os.path.dirname(__file__)

# Old files to remove/clear
OLD_EMBEDDINGS = os.path.join(DATA_DIR, "embeddings_cache.json")
OLD_KB_FILES = [
    "knowledge_base_with_faq.json",
    "knowledge_base.json",
    "knowledge_base_full.json",
    "knowledge_base_compact.json",
    "knowledge_base_unified.json",
    "unified_knowledge.json",
    "excel_data.json",
    "faq.json",
]


def _build_document_text(test):
    parts = [
        test.get("analysis_name_ar") or "",
        test.get("analysis_name_en") or "",
        test.get("description") or "",
        test.get("symptoms") or "",
        test.get("category") or "",
        test.get("sample_type") or "",
        test.get("preparation") or "",
        test.get("complementary_tests") or "",
    ]
    return " ".join(str(p).strip() for p in parts if p).strip()


def build(raise_on_error: bool = False) -> bool:
    """
    Build RAG system. Returns True on success, False on failure.
    When raise_on_error=True, raises instead of sys.exit.
    """
    print("=" * 70)
    print("🔧 Build RAG System - analysis_file.xlsx as sole source")
    print("=" * 70)
    
    # Step 1: Remove old indexes
    print("\nStep 1: Removing old indexes...")
    if os.path.exists(OLD_EMBEDDINGS):
        os.remove(OLD_EMBEDDINGS)
        print("   [OK] Removed embeddings_cache.json")
    else:
        print("   (no old embeddings to remove)")
    
    # Step 2: Build knowledge base from analysis_file.xlsx
    print("\nStep 2: Loading analysis_file.xlsx and matching prices...")
    try:
        from app.data.analysis_loader import build_rag_knowledge_base
        out_path = build_rag_knowledge_base()
        print(f"   [OK] Saved {out_path}")
    except FileNotFoundError as e:
        print(f"   ❌ ERROR: {e}")
        print("   Please add analysis_file.xlsx to app/data/ and run again.")
        if raise_on_error:
            raise
        sys.exit(1)
    except Exception as e:
        logger.exception("Failed to build knowledge base")
        if raise_on_error:
            raise
        sys.exit(1)
    
    # Step 3: Load and generate embeddings
    print("\nStep 3: Generating embeddings...")
    rag_path = os.path.join(DATA_DIR, "rag_knowledge_base.json")
    with open(rag_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    tests = data.get("tests", [])
    
    try:
        from app.services.embeddings_service import get_embeddings
    except Exception as e:
        print(f"   ❌ Embeddings service not available: {e}")
        if raise_on_error:
            raise
        sys.exit(1)
    
    texts = [_build_document_text(t) for t in tests]
    print(f"   Computing embeddings for {len(texts)} documents...")
    embeddings = get_embeddings(texts)
    
    if len(embeddings) != len(tests):
        print("   [ERROR] Embeddings count mismatch")
        if raise_on_error:
            raise ValueError("Embeddings count mismatch")
        sys.exit(1)
    
    emb_path = os.path.join(DATA_DIR, "rag_embeddings.json")
    with open(emb_path, "w", encoding="utf-8") as f:
        json.dump({
            "test_embeddings": embeddings,
            "version": 1,
        }, f, ensure_ascii=False)
    print(f"   ✅ Saved {emb_path}")
    
    print("\n" + "=" * 70)
    print("✅ RAG system built successfully!")
    print("   - Knowledge: rag_knowledge_base.json")
    print("   - Embeddings: rag_embeddings.json")
    print("   - Old indexes removed")
    print("\n[NOTE] Old knowledge files (knowledge_base_with_faq.json, etc.) are NOT deleted")
    print("   to preserve price-matching source. You may remove them manually if desired.")
    print("=" * 70)
    return True


def main():
    """CLI entry point."""
    build(raise_on_error=False)


if __name__ == "__main__":
    main()
