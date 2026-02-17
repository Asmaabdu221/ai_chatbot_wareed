"""
Semantic Search Module
======================
Uses precomputed embeddings for similarity search over tests and FAQs.
Falls back to no results if embeddings are not available.
"""

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Path to precomputed embeddings (same dir as this module)
EMBEDDINGS_CACHE_PATH = os.path.join(os.path.dirname(__file__), "embeddings_cache.json")

# Knowledge base path (same as knowledge_loader_v2)
KNOWLEDGE_BASE_PATH = os.path.join(os.path.dirname(__file__), "knowledge_base_with_faq.json")
FALLBACK_KB_PATH = os.path.join(os.path.dirname(__file__), "knowledge.json")


def _norm(v: List[float]) -> float:
    """Euclidean norm."""
    return sum(x * x for x in v) ** 0.5


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """Cosine similarity between two vectors. Returns 0 if either norm is 0."""
    na = _norm(a)
    nb = _norm(b)
    if na == 0 or nb == 0:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (na * nb)


def _build_test_doc(test: Dict[str, Any]) -> str:
    """Build a single searchable text for a test."""
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


def _build_faq_doc(faq: Dict[str, Any]) -> str:
    """Build a single searchable text for an FAQ."""
    q = faq.get("question") or ""
    a = faq.get("answer") or ""
    return f"{q} {a}".strip()


def _load_json_robust(path: str) -> Optional[Dict]:
    """Load JSON file; allow NaN/inf by replacing with null for compatibility."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except Exception as e:
        logger.warning("Could not read KB file %s: %s", path, e)
        return None
    # Replace JavaScript-style NaN/Infinity so standard json.load works
    text = re.sub(r":\s*NaN\b", ": null", text)
    text = re.sub(r":\s*-?Infinity\b", ": null", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning("Invalid JSON in %s: %s", path, e)
        return None


def _load_kb() -> Tuple[List[Dict], List[Dict]]:
    """Load tests and faqs from knowledge base JSON."""
    path = KNOWLEDGE_BASE_PATH if os.path.exists(KNOWLEDGE_BASE_PATH) else FALLBACK_KB_PATH
    if not os.path.exists(path):
        return [], []
    data = _load_json_robust(path)
    if not data:
        return [], []
    tests = data.get("tests") or []
    faqs = data.get("faqs") or []
    return tests, faqs


def _load_embeddings_cache() -> Optional[Dict[str, Any]]:
    """Load embeddings from cache file. Returns None if missing or invalid."""
    if not os.path.exists(EMBEDDINGS_CACHE_PATH):
        return None
    try:
        with open(EMBEDDINGS_CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("Failed to load embeddings cache: %s", e)
        return None


def semantic_search(
    query: str,
    max_tests: int = 5,
    max_faqs: int = 3,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Run semantic search over tests and FAQs using precomputed embeddings.

    Args:
        query: User query text.
        max_tests: Maximum number of tests to return.
        max_faqs: Maximum number of FAQs to return.

    Returns:
        Dict with keys 'tests' and 'faqs'. Each value is a list of
        { 'test'|'faq': item, 'score': float }. Empty if no cache.
    """
    out = {"tests": [], "faqs": []}
    cache = _load_embeddings_cache()
    if not cache:
        return out

    test_embeddings = cache.get("test_embeddings") or []
    faq_embeddings = cache.get("faq_embeddings") or []
    tests, faqs = _load_kb()

    if len(test_embeddings) != len(tests) or len(faq_embeddings) != len(faqs):
        logger.warning("Embeddings cache size mismatch with KB; skipping semantic search.")
        return out

    # Embed query (lazy import to avoid circular deps and to run build script without app)
    try:
        from app.services.embeddings_service import get_embedding
    except Exception:
        logger.warning("Embeddings service not available.")
        return out

    q_emb = get_embedding(query)
    if not q_emb:
        return out

    # Tests: cosine similarity and sort
    test_scores: List[Tuple[int, float]] = []
    for i, emb in enumerate(test_embeddings):
        if emb:
            score = _cosine_similarity(q_emb, emb)
            test_scores.append((i, score))
    test_scores.sort(key=lambda x: x[1], reverse=True)
    for i, score in test_scores[:max_tests]:
        out["tests"].append({"test": tests[i], "score": score})

    # FAQs
    faq_scores: List[Tuple[int, float]] = []
    for i, emb in enumerate(faq_embeddings):
        if emb:
            score = _cosine_similarity(q_emb, emb)
            faq_scores.append((i, score))
    faq_scores.sort(key=lambda x: x[1], reverse=True)
    for i, score in faq_scores[:max_faqs]:
        out["faqs"].append({"faq": faqs[i], "score": score})

    return out


def is_semantic_search_available() -> bool:
    """Return True if embeddings cache exists and matches current KB size."""
    cache = _load_embeddings_cache()
    if not cache:
        return False
    tests, faqs = _load_kb()
    te = cache.get("test_embeddings") or []
    fe = cache.get("faq_embeddings") or []
    return len(te) == len(tests) and len(fe) == len(faqs)
