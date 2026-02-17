"""
Build Embeddings Cache for Semantic Search
==========================================
Run once to precompute embeddings for all tests and FAQs, then save to
app/data/embeddings_cache.json. Requires OPENAI_API_KEY in environment.

Usage (from project root):
  python -m app.data.build_embeddings
"""

import json
import logging
import os
import sys

# Ensure app is on path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

KNOWLEDGE_BASE_PATH = os.path.join(os.path.dirname(__file__), "knowledge_base_with_faq.json")
FALLBACK_KB_PATH = os.path.join(os.path.dirname(__file__), "knowledge.json")
EMBEDDINGS_CACHE_PATH = os.path.join(os.path.dirname(__file__), "embeddings_cache.json")


def _build_test_doc(test):
    parts = [
        test.get("analysis_name_ar") or "",
        test.get("analysis_name_en") or "",
        test.get("description") or "",
        test.get("symptoms") or "",
        test.get("category") or "",
        test.get("sample_type") or "",
        test.get("preparation") or "",
    ]
    return " ".join(p for p in parts if p).strip()


def _build_faq_doc(faq):
    q = faq.get("question") or ""
    a = faq.get("answer") or ""
    return f"{q} {a}".strip()


def _load_json_robust(path):
    import re
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    text = re.sub(r":\s*NaN\b", ": null", text)
    text = re.sub(r":\s*-?Infinity\b", ": null", text)
    return json.loads(text)


def main():
    path = KNOWLEDGE_BASE_PATH if os.path.exists(KNOWLEDGE_BASE_PATH) else FALLBACK_KB_PATH
    if not os.path.exists(path):
        logger.error("Knowledge base not found: %s", path)
        sys.exit(1)

    try:
        data = _load_json_robust(path)
    except Exception as e:
        logger.error("Failed to load knowledge base: %s", e)
        sys.exit(1)
    tests = data.get("tests") or []
    faqs = data.get("faqs") or []

    logger.info("Tests: %s, FAQs: %s", len(tests), len(faqs))

    from app.services.embeddings_service import get_embeddings

    test_texts = [_build_test_doc(t) for t in tests]
    faq_texts = [_build_faq_doc(f) for f in faqs]

    logger.info("Computing test embeddings...")
    test_embeddings = get_embeddings(test_texts)
    if len(test_embeddings) != len(tests):
        logger.error("Test embeddings count mismatch")
        sys.exit(1)

    logger.info("Computing FAQ embeddings...")
    faq_embeddings = get_embeddings(faq_texts)
    if len(faq_embeddings) != len(faqs):
        logger.error("FAQ embeddings count mismatch")
        sys.exit(1)

    cache = {
        "test_embeddings": test_embeddings,
        "faq_embeddings": faq_embeddings,
        "version": 1,
    }
    with open(EMBEDDINGS_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)

    logger.info("Saved embeddings to %s", EMBEDDINGS_CACHE_PATH)


if __name__ == "__main__":
    main()
