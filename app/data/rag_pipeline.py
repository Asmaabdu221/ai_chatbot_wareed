"""
RAG Pipeline - Hybrid Retrieval (Semantic + Lexical)
====================================================
- Semantic: Embedding-based cosine similarity (good for conceptual queries)
- Lexical: Fuzzy matching on test names (good for short queries, acronyms, partial names)
- Combines both to fix retrieval for: "NIPT", "Ferritin?", "Vitamin D test?", "HbA1c"
- Similarity threshold applies to semantic; lexical has its own min_score
"""

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from app.utils.arabic_normalizer import normalize_for_matching

logger = logging.getLogger(__name__)

# Paths
RAG_KNOWLEDGE_PATH = os.path.join(os.path.dirname(__file__), "rag_knowledge_base.json")
RAG_EMBEDDINGS_PATH = os.path.join(os.path.dirname(__file__), "rag_embeddings.json")

# Semantic: cosine similarity threshold (0-1). 0.58 improves recall for فيتامين د، نوم، مزاج، معدة
DEFAULT_SIMILARITY_THRESHOLD = 0.58

# Lexical: minimum fuzzy score (0-100) to accept a match
LEXICAL_MIN_SCORE = 50

# Message when no relevant info found (professional, no "system" mention)
NO_INFO_MESSAGE = "عذراً، لا تتوفر لدي معلومات عن ذلك حالياً."


def _load_json_robust(path: str) -> Optional[Dict]:
    """Load JSON; handle NaN/Infinity."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except Exception as e:
        logger.warning("Could not read %s: %s", path, e)
        return None
    text = re.sub(r":\s*NaN\b", ": null", text)
    text = re.sub(r":\s*-?Infinity\b", ": null", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning("Invalid JSON in %s: %s", path, e)
        return None


def _build_document_text(test: Dict[str, Any]) -> str:
    """Build searchable text from a test record (for embedding)."""
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


def _norm(v: List[float]) -> float:
    """Euclidean norm."""
    return sum(x * x for x in v) ** 0.5


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """Cosine similarity between two vectors."""
    na = _norm(a)
    nb = _norm(b)
    if na == 0 or nb == 0:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (na * nb)


def load_rag_knowledge() -> Tuple[List[Dict], Dict]:
    """Load RAG knowledge base. Raises if not built."""
    data = _load_json_robust(RAG_KNOWLEDGE_PATH)
    if not data:
        raise FileNotFoundError(
            f"RAG knowledge base not found at {RAG_KNOWLEDGE_PATH}. "
            "Run: python -m app.data.build_rag_system"
        )
    tests = data.get("tests", [])
    metadata = data.get("metadata", {})
    return tests, metadata


def load_embeddings() -> Optional[Dict]:
    """Load precomputed embeddings."""
    return _load_json_robust(RAG_EMBEDDINGS_PATH)


def is_rag_ready() -> bool:
    """Check if RAG system is built and ready."""
    if not os.path.exists(RAG_KNOWLEDGE_PATH):
        return False
    emb = load_embeddings()
    if not emb:
        return False
    tests, _ = load_rag_knowledge()
    te = emb.get("test_embeddings") or []
    return len(te) == len(tests)


def _extract_search_terms(query: str) -> str:
    """
    Extract core search terms from query for lexical search.
    Removes common question phrases to improve matching for short test names.
    """
    q = (query or "").strip()
    if not q:
        return ""
    q_lower = q.lower()
    # Normalize vitamin D variants: "فيتامين دال" -> "فيتامين د"
    if "فيتامين دال" in q_lower or "vitamin d" in q_lower:
        q_lower = q_lower.replace("فيتامين دال", "فيتامين د").replace("vitamin d", "فيتامين د")
    # Remove common Arabic/English question prefixes (case-insensitive)
    patterns = [
        r"^(do you have|do you offer|is there|have you got|can you do)\s+",
        r"^(هل لديكم|هل تتوفر|هل يوجد|عندكم|عندنا|عندي|لدي|نفسر|نقدم)\s*",
        r"^(تحليل|فحص|اختبار|تحاليل|فحوص)\s*",
        r"^\s*(تحليل|فحص|اختبار)\s*",  # after other removals, e.g. " تحليل nipt" -> "nipt"
        r"\s*(test|analysis|فحص|تحليل|تحاليل)\s*$",
        r"^what is\s+(the\s+)?",
        r"^ما هو\s+(تحليل\s+)?",
        r"^\?+\s*|\s*\?+$",  # leading/trailing ?
        # Symptom-based query cleanup: "ايش التحاليل اللي ممكن اسويها", "ماهي التحاليل"
        r"\s*(ايش|اللي|ممكن|اسويها|ماهي|ماهو)\s*",
        r"\s*(التحاليل|الفحوصات)\s*(اللي|التي)?\s*(ممكن|يمكن)?\s*(اسويها|أعملها)?\s*$",
    ]
    for pat in patterns:
        q_lower = re.sub(pat, " ", q_lower, flags=re.IGNORECASE)
    q_lower = re.sub(r"\s+", " ", q_lower).strip()
    return q_lower if q_lower else (query or "").strip().lower()


def _lexical_retrieve(
    query: str,
    tests: List[Dict[str, Any]],
    max_results: int = 5,
    min_score: int = LEXICAL_MIN_SCORE,
) -> List[Dict[str, Any]]:
    """
    Lexical/fuzzy search on test names. Handles short queries, acronyms, partial names.
    Returns list of {test, score} where score is 0-100 (rapidfuzz).
    """
    from rapidfuzz import fuzz

    search_terms = _extract_search_terms(query)
    if not search_terms:
        search_terms = (query or "").strip().lower()
    if not search_terms:
        return []

    query_norm = normalize_for_matching(search_terms)
    raw_norm = normalize_for_matching((query or "").strip().lower())
    results = []

    for test in tests:
        name_ar = (test.get("analysis_name_ar") or "").strip()
        name_en = (test.get("analysis_name_en") or "").strip()
        desc = (test.get("description") or "").strip()
        symptoms = (test.get("symptoms") or "").strip()
        category = (test.get("category") or "").strip()
        comp = (test.get("complementary_tests") or "").strip()
        related = (test.get("alternative_tests") or "").strip() + " " + (test.get("related_tests") or "").strip()
        # Include symptoms, category, complementary, related for better matching (فيتامين د، نوم، مزاج، معدة)
        searchable = f"{name_ar} {name_en} {desc} {symptoms} {category} {comp} {related}".lower()

        max_score = 0
        # Partial ratio: query contained in field (e.g. "nipt" in "Noninvasive prenatal testing (NIPT)")
        for qn in (query_norm, raw_norm):
            if not qn or len(qn) < 2:
                continue
            if name_ar:
                s = fuzz.partial_ratio(qn, normalize_for_matching(name_ar))
                max_score = max(max_score, s)
            if name_en:
                s = fuzz.partial_ratio(qn, name_en.lower())
                max_score = max(max_score, s)
            if searchable:
                s = fuzz.partial_ratio(qn, normalize_for_matching(searchable))
                max_score = max(max_score, s)
        # Token set ratio: better for multi-word queries (e.g. "vitamin d" vs "Vitamine K")
        if len(query_norm.split()) >= 2:
            if name_ar:
                s = fuzz.token_set_ratio(query_norm, normalize_for_matching(name_ar))
                max_score = max(max_score, s)
            if name_en:
                s = fuzz.token_set_ratio(query_norm, name_en.lower())
                max_score = max(max_score, s)

        # Boost: query (or key part) contained in name
        for qn in (query_norm, raw_norm):
            if not qn or len(qn) < 2:
                continue
            if name_ar and qn in normalize_for_matching(name_ar):
                max_score = max(max_score, 90)
            if name_en and qn in name_en.lower():
                max_score = max(max_score, 90)

        if max_score >= min_score:
            results.append({"test": test, "score": max_score / 100.0, "source": "lexical"})

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:max_results]


def retrieve(
    query: str,
    max_results: int = 5,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> Tuple[List[Dict], bool]:
    """
    Hybrid retrieval: semantic + lexical.
    Returns merged results; has_sufficient = True if semantic OR lexical finds a match.
    """
    tests, _ = load_rag_knowledge()

    # Semantic search
    semantic_results: List[Dict] = []
    emb_data = load_embeddings()
    if emb_data:
        test_embeddings = emb_data.get("test_embeddings") or []
        if len(test_embeddings) == len(tests):
            try:
                from app.services.embeddings_service import get_embedding
                q_emb = get_embedding(query)
                if q_emb:
                    scored = []
                    for i, emb in enumerate(test_embeddings):
                        if emb:
                            sim = _cosine_similarity(q_emb, emb)
                            scored.append((i, sim))
                    scored.sort(key=lambda x: x[1], reverse=True)
                    for i, score in scored[:max_results]:
                        semantic_results.append({
                            "test": tests[i],
                            "score": score,
                            "source": "semantic",
                        })
            except Exception as e:
                logger.debug("Semantic search failed: %s", e)

    # Lexical search (always runs; robust for short queries)
    lexical_results = _lexical_retrieve(
        query,
        tests,
        max_results=max_results,
        min_score=LEXICAL_MIN_SCORE,
    )

    # Merge: by test key, keep best score per test
    def _key(t: Dict) -> str:
        return str(t.get("analysis_name_ar", "")) + "|" + str(t.get("analysis_name_en", ""))

    best_by_key: Dict[str, Dict] = {}
    lex_min = LEXICAL_MIN_SCORE / 100.0

    for r in semantic_results + lexical_results:
        t = r["test"]
        k = _key(t)
        score = r["score"]
        src = r.get("source", "semantic")
        if k not in best_by_key or score > best_by_key[k]["score"]:
            best_by_key[k] = {"test": t, "score": score, "source": src}

    # Include if passes semantic threshold OR lexical threshold
    merged = [
        v for v in best_by_key.values()
        if (v["score"] >= similarity_threshold)
        or (v.get("source") == "lexical" and v["score"] >= lex_min)
    ]
    merged.sort(key=lambda x: x["score"], reverse=True)
    merged = merged[:max_results]

    has_sufficient = any(
        r["score"] >= similarity_threshold
        or (r.get("source") == "lexical" and r["score"] >= lex_min)
        for r in merged
    )

    return merged, has_sufficient


def get_grounded_context(
    user_message: str,
    max_tests: int = 3,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    include_prices: bool = True,
    use_cache: bool = True,
) -> Tuple[str, bool]:
    """
    Get context for AI - ONLY from retrieved knowledge.
    
    Returns:
        (context_string, has_relevant_info)
        If has_relevant_info is False, context will indicate no info.
    """
    if use_cache:
        try:
            from app.services.context_cache import get_context_cache
            import hashlib
            raw = f"rag|{user_message.strip().lower()}|{max_tests}|{similarity_threshold}|{include_prices}"
            key = hashlib.sha256(raw.encode("utf-8")).hexdigest()
            cached = get_context_cache().get(key)
            if cached is not None:
                return cached, True
        except Exception:
            pass
    
    results, has_sufficient = retrieve(
        user_message,
        max_results=max_tests,
        similarity_threshold=similarity_threshold,
    )
    
    if not has_sufficient or not results:
        return "", False

    # Include results that pass semantic OR lexical threshold
    lex_min = LEXICAL_MIN_SCORE / 100.0
    above_threshold = [
        r for r in results
        if r["score"] >= similarity_threshold
        or (r.get("source") == "lexical" and r["score"] >= lex_min)
    ]
    if not above_threshold:
        return "", False
    
    parts = ["📊 **معلومات التحاليل ذات الصلة:**\n"]
    for i, r in enumerate(above_threshold[:max_tests], 1):
        test = r["test"]
        score = r["score"]
        lines = []
        name_ar = test.get("analysis_name_ar", "غير متوفر")
        name_en = test.get("analysis_name_en", "")
        lines.append(f"🔬 **{name_ar}**")
        if name_en:
            lines.append(f"   ({name_en})")
        desc = test.get("description")
        if desc:
            lines.append(f"\n📝 **الوصف:** {desc}")
        if include_prices:
            price = test.get("price")
            if price is not None:
                lines.append(f"\n💰 **السعر:** {price} جنيه")
        sample = test.get("sample_type")
        if sample:
            lines.append(f"\n🧪 **نوع العينة:** {sample}")
        category = test.get("category")
        if category:
            lines.append(f"\n📂 **التصنيف:** {category}")
        symptoms = test.get("symptoms")
        if symptoms:
            lines.append(f"\n⚕️ **الأعراض:** {symptoms}")
        prep = test.get("preparation")
        if prep:
            lines.append(f"\n📋 **التحضير:** {prep}")
        comp = test.get("complementary_tests")
        if comp:
            lines.append(f"\n🔗 **تحاليل مكملة:** {comp}")
        parts.append(f"\n{i}. " + "\n".join(lines) + "\n" + "-" * 50 + "\n")
    
    context_str = "".join(parts)
    if use_cache:
        try:
            from app.services.context_cache import get_context_cache
            import hashlib
            raw = f"rag|{user_message.strip().lower()}|{max_tests}|{similarity_threshold}|{include_prices}"
            key = hashlib.sha256(raw.encode("utf-8")).hexdigest()
            get_context_cache().set(key, context_str)
        except Exception:
            pass
    
    return context_str, True
