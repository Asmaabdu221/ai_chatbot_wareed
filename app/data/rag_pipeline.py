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
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from app.core.runtime_paths import TESTS_CHUNKS_PATH, path_exists
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
NO_INFO_MESSAGE = "عذراً، حالياً ما عندنا معلومات كافية عن هذا الطلب."

SYNONYMS_PATH = Path("app/data/runtime/synonyms/synonyms_ar.json")
_RAG_SYNONYMS_CACHE = None
_RAG_CONCEPT_INDEX_CACHE = None


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


def load_runtime_chunks_jsonl(path):
    """
    Reads JSONL chunks {id, text, metadata}
    Returns list[dict]
    """
    import json

    chunks = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            chunks.append(json.loads(line))
    return chunks


def load_rag_synonyms():
    global _RAG_SYNONYMS_CACHE
    if _RAG_SYNONYMS_CACHE is not None:
        return _RAG_SYNONYMS_CACHE
    if path_exists(SYNONYMS_PATH):
        with open(SYNONYMS_PATH, "r", encoding="utf-8") as f:
            _RAG_SYNONYMS_CACHE = json.load(f)
            return _RAG_SYNONYMS_CACHE
    _RAG_SYNONYMS_CACHE = {}
    return _RAG_SYNONYMS_CACHE


def expand_test_query(text: str) -> str:
    raw_query = text or ""
    query_norm_full = _safe_normalize_for_matching(raw_query)
    search_terms = _extract_search_terms(raw_query)
    query_key = _safe_normalize_for_matching(search_terms or query_norm_full)
    if not query_key:
        return ""
    # Broad Arabic questions are handled by concept expansion in retrieve().
    # Keep this stage lightweight to avoid overly long expansions.
    if _contains_arabic(query_key) and len(query_key.split()) >= 2:
        return query_key

    synonyms = load_rag_synonyms()
    tests_syn = synonyms.get("tests") if isinstance(synonyms, dict) else {}
    if not isinstance(tests_syn, dict):
        return query_key

    scored_matches: List[Tuple[float, str, List[str]]] = []

    max_aliases_per_concept = 80
    max_alias_len = 140
    for concept in tests_syn.values():
        if not isinstance(concept, dict):
            continue
        aliases = concept.get("aliases") or []
        if not isinstance(aliases, list):
            continue

        matched_aliases: List[str] = []
        best_score = 0.0
        for alias in aliases[:max_aliases_per_concept]:
            if len(str(alias or "")) > max_alias_len:
                continue
            alias_n = _safe_normalize_for_matching(str(alias))
            if not alias_n or len(alias_n) < 3:
                continue
            if alias_n == query_key:
                matched_aliases.append(alias_n)
                best_score = max(best_score, 1.0)
            elif len(query_key) >= 3 and query_key in alias_n:
                matched_aliases.append(alias_n)
                best_score = max(best_score, 0.92)
            elif len(alias_n) >= 3 and alias_n in query_key:
                matched_aliases.append(alias_n)
                best_score = max(best_score, 0.9)
            else:
                q_tokens = set(query_key.split())
                a_tokens = set(alias_n.split())
                if q_tokens and a_tokens:
                    overlap = len(q_tokens & a_tokens) / max(1, len(q_tokens))
                    if overlap >= 0.5:
                        matched_aliases.append(alias_n)
                        best_score = max(best_score, 0.75 + min(0.2, overlap * 0.2))

        if not matched_aliases:
            continue

        display_n = _safe_normalize_for_matching(str(concept.get("display_name") or ""))
        scored_matches.append((best_score, display_n, matched_aliases[:3]))

    scored_matches.sort(key=lambda x: x[0], reverse=True)
    scored_matches = scored_matches[:3]

    additions: List[str] = []
    seen: Set[str] = {query_key}
    for _score, display_n, aliases_n in scored_matches:
        if display_n and display_n not in seen:
            seen.add(display_n)
            additions.append(display_n)
        for a in aliases_n:
            if a not in seen:
                seen.add(a)
                additions.append(a)

    return " ".join([query_key, *additions]).strip()


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if v is not None]
    if isinstance(value, str):
        if not value.strip():
            return []
        return [value]
    return [str(value)]


def _build_concept_light_index() -> List[Dict[str, Any]]:
    global _RAG_CONCEPT_INDEX_CACHE
    if _RAG_CONCEPT_INDEX_CACHE is not None:
        return _RAG_CONCEPT_INDEX_CACHE

    synonyms = load_rag_synonyms()
    concepts = synonyms.get("concepts") if isinstance(synonyms, dict) else {}
    if not isinstance(concepts, dict):
        _RAG_CONCEPT_INDEX_CACHE = []
        return _RAG_CONCEPT_INDEX_CACHE

    index: List[Dict[str, Any]] = []
    for concept_key, concept in concepts.items():
        if not isinstance(concept, dict):
            continue

        display = str(concept.get("display_name") or "").strip()
        aliases = _as_list(concept.get("aliases"))[:3]
        related_tests = _as_list(concept.get("related_tests"))[:5]
        signals = concept.get("signals") if isinstance(concept.get("signals"), dict) else {}
        symptom_signals = _as_list(signals.get("symptoms"))[:3]
        preparation_signals = _as_list(signals.get("preparation"))[:3]
        category_signals = _as_list(signals.get("category"))[:3]
        benefit_signals = _as_list(signals.get("benefit"))[:3]

        terms: List[str] = []
        seen_terms: Set[str] = set()

        def _add_term(v: str) -> None:
            n = _safe_normalize_for_matching(v)
            if not n or len(n) < 2 or len(n) > 120 or n in seen_terms:
                return
            seen_terms.add(n)
            terms.append(n)

        _add_term(display)
        for source in (
            aliases,
            related_tests,
            symptom_signals,
            preparation_signals,
            category_signals,
            benefit_signals,
        ):
            for item in source:
                _add_term(str(item))

        if not terms:
            continue

        index.append(
            {
                "key": str(concept_key),
                "display_name": display,
                "aliases": aliases,
                "related_tests": related_tests,
                "signals": {
                    "symptoms": symptom_signals,
                    "preparation": preparation_signals,
                    "category": category_signals,
                    "benefit": benefit_signals,
                },
                "terms": terms,
            }
        )

    _RAG_CONCEPT_INDEX_CACHE = index
    return _RAG_CONCEPT_INDEX_CACHE


def _collect_concept_matches(query_norm: str, max_matches: int = 8) -> List[Dict[str, Any]]:
    if not query_norm:
        return []

    concept_index = _build_concept_light_index()
    if not concept_index:
        return []

    q_tokens = set(query_norm.split()[:16])
    q_tokens_long = {t for t in q_tokens if len(t) >= 2}
    matches: List[Dict[str, Any]] = []

    for concept in concept_index:
        display = str(concept.get("display_name") or "").strip()
        aliases = _as_list(concept.get("aliases"))
        related_tests = _as_list(concept.get("related_tests"))
        sig = concept.get("signals") if isinstance(concept.get("signals"), dict) else {}
        symptom_signals = _as_list(sig.get("symptoms"))
        preparation_signals = _as_list(sig.get("preparation"))
        category_signals = _as_list(sig.get("category"))
        benefit_signals = _as_list(sig.get("benefit"))
        candidates = _as_list(concept.get("terms"))

        best_score = 0.0
        matched_terms: List[str] = []
        for term in candidates:
            term_n = str(term or "").strip()
            if not term_n:
                continue
            if q_tokens_long and not any((tk in term_n) or (term_n in tk) for tk in q_tokens_long):
                if len(term_n) >= 4 and term_n not in query_norm:
                    continue
            if term_n == query_norm:
                best_score = max(best_score, 1.0)
                matched_terms.append(term_n)
                continue
            if len(query_norm) >= 3 and query_norm in term_n:
                best_score = max(best_score, 0.93)
                matched_terms.append(term_n)
                continue
            if len(term_n) >= 3 and term_n in query_norm:
                best_score = max(best_score, 0.9)
                matched_terms.append(term_n)
                continue
            t_tokens = set(term_n.split())
            if q_tokens and t_tokens:
                if not (q_tokens & t_tokens):
                    continue
                overlap = len(q_tokens & t_tokens) / max(1, min(len(q_tokens), len(t_tokens)))
                if overlap >= 0.5:
                    best_score = max(best_score, 0.72 + min(0.2, overlap * 0.2))
                    matched_terms.append(term_n)

        if best_score < 0.65:
            continue

        matches.append(
            {
                "key": str(concept.get("key") or ""),
                "score": best_score,
                "display_name": display,
                "aliases": aliases,
                "related_tests": related_tests,
                "signals": {
                    "symptoms": symptom_signals,
                    "preparation": preparation_signals,
                    "category": category_signals,
                    "benefit": benefit_signals,
                },
                "matched_terms": matched_terms[:6],
            }
        )

    matches.sort(key=lambda x: x["score"], reverse=True)
    return matches[:max_matches]


def expand_query_with_concepts(text: str) -> str:
    query_norm = _safe_normalize_for_matching(text or "")
    if not query_norm:
        return ""
    if _contains_arabic(query_norm) and len(query_norm.split()) >= 2:
        return query_norm

    matches = _collect_concept_matches(query_norm, max_matches=6)
    if not matches:
        return query_norm

    additions: List[str] = []
    seen: Set[str] = {query_norm}
    max_terms = 60
    max_chars = 1200

    for match in matches:
        fields = [
            match.get("display_name"),
            *(match.get("aliases") or []),
            *(match.get("related_tests") or []),
            *((match.get("signals") or {}).get("symptoms") or []),
            *((match.get("signals") or {}).get("preparation") or []),
            *((match.get("signals") or {}).get("category") or []),
        ]
        for item in fields:
            item_n = _safe_normalize_for_matching(str(item or ""))
            if not item_n or len(item_n) < 2 or item_n in seen:
                continue
            seen.add(item_n)
            additions.append(item_n)
            if len(additions) >= max_terms:
                break
            if len(" ".join([query_norm, *additions])) >= max_chars:
                break
        if len(additions) >= max_terms or len(" ".join([query_norm, *additions])) >= max_chars:
            break

    return " ".join([query_norm, *additions]).strip()


def _query_asks_preparation(text: str) -> bool:
    t = _safe_normalize_for_matching(text or "")
    if not t:
        return False
    keywords = (
        "صيام",
        "صايم",
        "تحضير",
        "قبل التحليل",
        "preparation",
        "fasting",
    )
    return any(k in t for k in keywords)


def _query_asks_symptoms(text: str) -> bool:
    t = _safe_normalize_for_matching(text or "")
    if not t:
        return False
    keywords = (
        "اعراض",
        "أعراض",
        "عرض",
        "symptom",
        "symptoms",
    )
    return any(_safe_normalize_for_matching(k) in t for k in keywords)


def _is_symptom_query(text_norm: str) -> bool:
    t = _safe_normalize_for_matching(text_norm or "")
    if not t:
        return False
    keywords = (
        "اعراض",
        "أعراض",
        "يشير",
        "سبب",
        "نقص",
        "ارتفاع",
        "انخفاض",
    )
    return any(_safe_normalize_for_matching(k) in t for k in keywords)


def _is_preparation_query(text_norm: str) -> bool:
    t = _safe_normalize_for_matching(text_norm or "")
    if not t:
        return False
    keywords = (
        "صيام",
        "صايم",
        "تحضير",
        "قبل التحليل",
        "يحتاج صيام",
        "بدون صيام",
    )
    return any(_safe_normalize_for_matching(k) in t for k in keywords)


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
    if path_exists(TESTS_CHUNKS_PATH):
        chunks = load_runtime_chunks_jsonl(TESTS_CHUNKS_PATH)
        tests: List[Dict[str, Any]] = []
        for chunk in chunks:
            metadata = chunk.get("metadata") or {}
            chunk_text = str(chunk.get("text") or "").strip()
            line_map: Dict[str, str] = {}
            for raw_line in chunk_text.splitlines():
                line = raw_line.strip()
                if ":" in line:
                    k, v = line.split(":", 1)
                    line_map[k.strip()] = v.strip()

            tests.append(
                {
                    "id": chunk.get("id"),
                    "analysis_name_ar": metadata.get("canonical_ar"),
                    "analysis_name_en": metadata.get("canonical_en"),
                    "canonical_name_clean": metadata.get("canonical_name_clean"),
                    "description": line_map.get("فائدة التحليل") or chunk_text,
                    "symptoms": line_map.get("الأعراض المرتبطة", ""),
                    "category": metadata.get("category_norm") or metadata.get("category"),
                    "sample_type": metadata.get("sample_type"),
                    "preparation": line_map.get("التحضير قبل التحليل", ""),
                    "complementary_tests": line_map.get("تحاليل مكملة", ""),
                    "related_tests": line_map.get("تحاليل قريبة", ""),
                    "alternative_tests": line_map.get("تحاليل بديلة", ""),
                    "price": metadata.get("price"),
                    "__chunk_text": chunk_text,
                }
            )

        logger.info("RAG runtime chunks loaded: %s", len(tests))
        logger.info("path: %s", TESTS_CHUNKS_PATH)
        return tests, {"source": "runtime_chunks", "path": str(TESTS_CHUNKS_PATH)}

    logger.info("RAG fallback -> rag_knowledge_base.json")
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
    if path_exists(TESTS_CHUNKS_PATH):
        try:
            return len(load_runtime_chunks_jsonl(TESTS_CHUNKS_PATH)) > 0
        except Exception:
            return False
    if not os.path.exists(RAG_KNOWLEDGE_PATH):
        return False
    try:
        tests, _ = load_rag_knowledge()
        return len(tests) > 0
    except Exception:
        return False


def _extract_search_terms(query: str) -> str:
    """
    Extract core search terms from query for lexical search.
    Removes common question phrases to improve matching for short test names.
    """
    q = (query or "").strip().lower()
    if not q:
        return ""

    q = q.replace("??????? ???", "??????? ?")
    q = re.sub(r"[??!.?,:;]+", " ", q)

    leading_phrases = [
        "?? ??",
        "?? ??",
        "???",
        "??",
        "??",
        "?? ????",
        "please",
        "what is",
        "do you have",
        "do you offer",
        "is there",
    ]
    for phrase in leading_phrases:
        if q.startswith(phrase + " "):
            q = q[len(phrase):].strip()

    drop_tokens = {
        "?????",
        "??????",
        "???",
        "????",
        "??????",
        "???????",
        "????????",
        "test",
        "analysis",
    }
    kept_tokens = [tok for tok in q.split() if tok not in drop_tokens]
    cleaned = " ".join(kept_tokens).strip()
    return cleaned or (query or "").strip().lower()

def _contains_arabic(text: str) -> bool:
    return any("\u0600" <= ch <= "\u06FF" for ch in (text or ""))


def _safe_normalize_for_matching(text: str) -> str:
    """
    Fast, safe normalization for retrieval.
    Uses a local normalization path to avoid runtime stalls in legacy normalizers.
    """
    raw = (text or "").strip()
    if not raw:
        return ""
    t = raw.lower()
    if _contains_arabic(t):
        t = re.sub(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]", "", t)
        t = re.sub(r"[\u0622\u0623\u0625\u0671]", "\u0627", t)
        t = re.sub(r"[\u0649\u064A]", "\u064A", t)
        t = re.sub(r"\u0640", "", t)
    else:
        try:
            return normalize_for_matching(t)
        except Exception:
            pass
    t = re.sub(r"[^\w\s\u0600-\u06FF]", " ", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def _extract_lab_code_tokens(query: str) -> List[str]:
    tokens: List[str] = []
    if not query:
        return tokens
    seen: Set[str] = set()
    for raw in re.findall(r"\b[A-Za-z]{2,10}\d{0,3}[A-Za-z]{0,3}\d{0,2}\b", query):
        token = raw.strip()
        if not token:
            continue
        upper = token.upper()
        if upper in {"TEST", "ANALYSIS", "PDF", "DOC", "DOCX", "TXT"}:
            continue
        if upper in seen:
            continue
        seen.add(upper)
        tokens.append(token)
    return tokens


def _structured_code_match(query: str, tests: List[Dict[str, Any]], max_results: int = 5) -> List[Dict[str, Any]]:
    tokens = _extract_lab_code_tokens(query)
    if not tokens:
        return []
    matches: List[Dict[str, Any]] = []
    for test in tests:
        name_en = (test.get("analysis_name_en") or "").lower()
        name_ar = _safe_normalize_for_matching((test.get("analysis_name_ar") or "").strip())
        related = (test.get("related_tests") or "").lower()
        alternative = (test.get("alternative_tests") or "").lower()
        composite = f"{name_en} {name_ar} {related} {alternative}"
        top_score = 0.0
        for token in tokens:
            tk = token.lower()
            if re.search(rf"\b{re.escape(tk)}\b", name_en):
                top_score = max(top_score, 0.99)
            elif re.search(rf"\b{re.escape(tk)}\b", composite):
                top_score = max(top_score, 0.93)
            elif tk in composite:
                top_score = max(top_score, 0.86)
        if top_score > 0:
            matches.append({"test": test, "score": top_score, "source": "structured"})
    matches.sort(key=lambda x: x["score"], reverse=True)
    return matches[:max_results]


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
    search_terms = _extract_search_terms(query)
    if not search_terms:
        return []

    query_norm = _safe_normalize_for_matching(search_terms)
    raw_norm = _safe_normalize_for_matching((query or "").strip().lower())
    code_tokens = _extract_lab_code_tokens(query)
    use_arabic_fast = _contains_arabic(query_norm) or _contains_arabic(raw_norm)
    fuzz = None
    if not use_arabic_fast:
        try:
            from rapidfuzz import fuzz as _rf_fuzz
            fuzz = _rf_fuzz
        except Exception:
            from difflib import SequenceMatcher

            class _FuzzFallback:
                @staticmethod
                def partial_ratio(a: str, b: str) -> int:
                    a = (a or "").lower()
                    b = (b or "").lower()
                    if not a or not b:
                        return 0
                    if a in b or b in a:
                        return 95
                    return int(SequenceMatcher(None, a, b).ratio() * 100)

                @staticmethod
                def token_set_ratio(a: str, b: str) -> int:
                    sa = set((a or "").lower().split())
                    sb = set((b or "").lower().split())
                    if not sa or not sb:
                        return 0
                    return int((len(sa & sb) / max(1, len(sa | sb))) * 100)

            fuzz = _FuzzFallback()
    logger.info(
        "normalization executed | raw_query='%s' | normalized_query='%s' | query_len=%s | normalized_len=%s | has_arabic=%s | detected_tokens=%s",
        (query or "")[:120],
        query_norm[:120],
        len(query or ""),
        len(query_norm),
        use_arabic_fast,
        code_tokens,
    )
    results = []

    def _token_overlap_score(a: str, b: str) -> int:
        if not a or not b:
            return 0
        if a in b or b in a:
            return 90
        at = set(a.split())
        bt = set(b.split())
        if not at or not bt:
            return 0
        return int((len(at & bt) / max(1, len(at))) * 100)

    for test in tests:
        name_ar = _safe_normalize_for_matching((test.get("analysis_name_ar") or "").strip())
        name_en = (test.get("analysis_name_en") or "").strip()
        desc = _safe_normalize_for_matching((test.get("description") or "").strip())
        symptoms = _safe_normalize_for_matching((test.get("symptoms") or "").strip())
        category = _safe_normalize_for_matching((test.get("category") or "").strip())
        comp = _safe_normalize_for_matching((test.get("complementary_tests") or "").strip())
        related = _safe_normalize_for_matching((test.get("alternative_tests") or "").strip() + " " + (test.get("related_tests") or "").strip())
        # Include symptoms, category, complementary, related for better matching (فيتامين د، نوم، مزاج، معدة)
        searchable = f"{name_ar} {name_en} {desc} {symptoms} {category} {comp} {related}".lower()

        max_score = 0
        for token in code_tokens:
            tk = token.lower()
            if re.search(rf"\b{re.escape(tk)}\b", (name_en or "").lower()):
                max_score = max(max_score, 99)
            elif re.search(rf"\b{re.escape(tk)}\b", searchable):
                max_score = max(max_score, 93)
        # Partial ratio: query contained in field (e.g. "nipt" in "Noninvasive prenatal testing (NIPT)")
        for qn in (query_norm, raw_norm):
            if not qn or len(qn) < 2:
                continue
            if use_arabic_fast:
                if name_ar:
                    max_score = max(max_score, _token_overlap_score(qn, name_ar))
                if name_en:
                    max_score = max(max_score, _token_overlap_score(qn, name_en.lower()))
                if searchable:
                    max_score = max(max_score, _token_overlap_score(qn, searchable))
            else:
                if name_ar:
                    s = fuzz.partial_ratio(qn, name_ar)
                    max_score = max(max_score, s)
                if name_en:
                    s = fuzz.partial_ratio(qn, name_en.lower())
                    max_score = max(max_score, s)
                if searchable:
                    s = fuzz.partial_ratio(qn, searchable)
                    max_score = max(max_score, s)
        # Token set ratio: better for multi-word queries (Latin path only)
        if not use_arabic_fast and len(query_norm.split()) >= 2:
            if name_ar:
                s = fuzz.token_set_ratio(query_norm, name_ar)
                max_score = max(max_score, s)
            if name_en:
                s = fuzz.token_set_ratio(query_norm, name_en.lower())
                max_score = max(max_score, s)

        # Boost: query (or key part) contained in name
        for qn in (query_norm, raw_norm):
            if not qn or len(qn) < 2:
                continue
            if name_ar and qn in name_ar:
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
    Lexical retrieval only.
    Returns merged results; has_sufficient = True if lexical finds a match.
    """
    tests, _ = load_rag_knowledge()
    lex_min = LEXICAL_MIN_SCORE / 100.0

    expanded_query = expand_test_query(query)
    concept_expanded_query = expand_query_with_concepts(expanded_query)
    print(
        "RAG_SYNONYM_DEBUG",
        {
            "original": str(query or "").encode("unicode_escape").decode("ascii"),
            "expanded": str(expanded_query[:200]).encode("unicode_escape").decode("ascii"),
        },
    )
    print(
        "RAG_CONCEPT_DEBUG",
        {
            "original": str(query or "").encode("unicode_escape").decode("ascii"),
            "expanded": str(concept_expanded_query[:250]).encode("unicode_escape").decode("ascii"),
        },
    )

    detected_tokens = _extract_lab_code_tokens(concept_expanded_query)
    structured_results = _structured_code_match(concept_expanded_query, tests, max_results=max_results)
    lexical_results = _lexical_retrieve(
        concept_expanded_query,
        tests,
        max_results=max_results,
        min_score=LEXICAL_MIN_SCORE,
    )
    lexical_results = structured_results + lexical_results
    lexical_has_sufficient = any(r["score"] >= lex_min for r in lexical_results)
    logger.info(
        "retrieval routing | detected_tokens=%s | structured_hits=%s | lexical_hits=%s | semantic_skipped=%s",
        detected_tokens,
        len(structured_results),
        len(lexical_results),
        True,
    )

    # Merge: by test key, keep best score per test
    def _key(t: Dict) -> str:
        return str(t.get("id", "")) + "|" + str(t.get("analysis_name_ar", "")) + "|" + str(t.get("analysis_name_en", ""))

    concept_matches = _collect_concept_matches(_safe_normalize_for_matching(expanded_query), max_matches=8)
    matched_concept_keys = [str(m.get("key") or "") for m in concept_matches if m.get("key")]
    strong_concept_aliases: Set[str] = set()
    prep_signals: Set[str] = set()
    symptom_signals: Set[str] = set()
    related_test_scores: Dict[str, float] = {}
    for m in concept_matches:
        base_weight = float(m.get("score") or 0.0)
        for alias in m.get("aliases", []):
            alias_n = _safe_normalize_for_matching(alias)
            if alias_n and len(alias_n) >= 4:
                strong_concept_aliases.add(alias_n)
        for rt in m.get("related_tests", []):
            rt_n = _safe_normalize_for_matching(rt)
            if not rt_n or len(rt_n) < 2:
                continue
            related_test_scores[rt_n] = max(related_test_scores.get(rt_n, 0.0), base_weight)
        sig = m.get("signals") or {}
        for p in sig.get("preparation", []):
            p_n = _safe_normalize_for_matching(p)
            if p_n and len(p_n) >= 3:
                prep_signals.add(p_n)
        for s in sig.get("symptoms", []):
            s_n = _safe_normalize_for_matching(s)
            if s_n and len(s_n) >= 3:
                symptom_signals.add(s_n)

    concept_related_tests = [
        name for name, _score in sorted(related_test_scores.items(), key=lambda x: x[1], reverse=True)[:20]
    ]
    print(
        "RAG_CONCEPT_MATCHES",
        {
            "query": str(query or "").encode("unicode_escape").decode("ascii"),
            "matched_concepts": [
                str(x).encode("unicode_escape").decode("ascii")
                for x in matched_concept_keys
            ],
            "related_tests": [
                str(x).encode("unicode_escape").decode("ascii")
                for x in concept_related_tests[:10]
            ],
        },
    )

    asks_preparation = _is_preparation_query(query)
    asks_symptoms = _is_symptom_query(query)

    def _related_test_match(names: List[str], related_items: List[str]) -> bool:
        if not names or not related_items:
            return False
        for n in names:
            if not n:
                continue
            for rt in related_items:
                if not rt:
                    continue
                if n == rt:
                    return True
                if len(rt) >= 3 and rt in n:
                    return True
                if len(n) >= 3 and n in rt:
                    return True
        return False

    best_by_key: Dict[str, Dict] = {}
    for r in lexical_results:
        t = r["test"]
        k = _key(t)
        score = r["score"]
        # Small boost when expanded query directly includes canonical test name fields.
        name_ar = _safe_normalize_for_matching(t.get("analysis_name_ar") or "")
        name_en = _safe_normalize_for_matching(t.get("analysis_name_en") or "")
        expanded_norm = _safe_normalize_for_matching(concept_expanded_query)
        canonical_clean = _safe_normalize_for_matching(t.get("canonical_name_clean") or "")
        if (
            (name_ar and name_ar in expanded_norm)
            or (name_en and name_en in expanded_norm)
            or (canonical_clean and canonical_clean in expanded_norm)
        ):
            score = min(1.0, score + 0.05)
        if _related_test_match([name_ar, name_en, canonical_clean], concept_related_tests):
            score = min(1.0, score + 0.10)
        chunk_text = _safe_normalize_for_matching(t.get("__chunk_text") or _build_document_text(t))
        if chunk_text:
            if strong_concept_aliases and any(a in chunk_text for a in strong_concept_aliases):
                score = min(1.0, score + 0.05)
            if asks_preparation and prep_signals and any(s in chunk_text for s in prep_signals):
                score = min(1.0, score + 0.05)
            if asks_symptoms and symptom_signals and any(s in chunk_text for s in symptom_signals):
                score = min(1.0, score + 0.05)
        src = r.get("source", "lexical")
        if k not in best_by_key or score > best_by_key[k]["score"]:
            best_by_key[k] = {"test": t, "score": score, "source": src}

    # Include lexical results passing lexical threshold (or explicit similarity threshold).
    merged = [
        v for v in best_by_key.values()
        if (v["score"] >= similarity_threshold)
        or (v.get("source") == "lexical" and v["score"] >= lex_min)
    ]
    merged.sort(key=lambda x: x["score"], reverse=True)
    merged = merged[:max_results]

    has_sufficient = any((r.get("source") == "lexical" and r["score"] >= lex_min) for r in merged)

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
        chunk_text = (test.get("__chunk_text") or "").strip()
        if chunk_text:
            parts.append(f"\n{i}. {chunk_text}\n" + "-" * 50 + "\n")
            continue

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


if __name__ == "__main__":
    chunks = load_runtime_chunks_jsonl(TESTS_CHUNKS_PATH)
    print("Loaded runtime chunks:", len(chunks))
