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
SITE_KNOWLEDGE_CHUNKS_PATH = Path("app/data/sources/web/site_knowledge_chunks_hard.jsonl")
_RAG_SYNONYMS_CACHE = None
_RAG_CONCEPT_INDEX_CACHE = None
_RAG_DIRECT_TEST_INDEX_CACHE = None
_SITE_KNOWLEDGE_CACHE = None


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


def load_site_knowledge_chunks() -> List[Dict[str, Any]]:
    global _SITE_KNOWLEDGE_CACHE
    if _SITE_KNOWLEDGE_CACHE is not None:
        return _SITE_KNOWLEDGE_CACHE
    if not os.path.exists(SITE_KNOWLEDGE_CHUNKS_PATH):
        _SITE_KNOWLEDGE_CACHE = []
        return _SITE_KNOWLEDGE_CACHE
    try:
        _SITE_KNOWLEDGE_CACHE = load_runtime_chunks_jsonl(SITE_KNOWLEDGE_CHUNKS_PATH)
    except Exception as exc:
        logger.warning("Could not load site knowledge chunks: %s", exc)
        _SITE_KNOWLEDGE_CACHE = []
    return _SITE_KNOWLEDGE_CACHE


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


def _is_code_like_token(token: str) -> bool:
    t = (token or "").strip()
    if not t:
        return False
    if re.fullmatch(r"[A-Za-z]{2,10}\d{0,3}[A-Za-z]{0,3}\d{0,2}", t):
        return True
    return bool(re.fullmatch(r"[A-Za-z0-9]{2,12}", t) and any(ch.isdigit() for ch in t))


def _build_direct_test_light_index() -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    global _RAG_DIRECT_TEST_INDEX_CACHE
    if _RAG_DIRECT_TEST_INDEX_CACHE is not None:
        return _RAG_DIRECT_TEST_INDEX_CACHE

    synonyms = load_rag_synonyms()
    tests_syn = synonyms.get("tests") if isinstance(synonyms, dict) else {}
    if not isinstance(tests_syn, dict):
        _RAG_DIRECT_TEST_INDEX_CACHE = ([], {})
        return _RAG_DIRECT_TEST_INDEX_CACHE

    entries: List[Dict[str, Any]] = []
    alias_freq: Dict[str, int] = {}
    for concept_key, concept in tests_syn.items():
        if not isinstance(concept, dict):
            continue

        display = str(concept.get("display_name") or "").strip()
        display_n = _safe_normalize_for_matching(display)
        key_n = _safe_normalize_for_matching(str(concept_key or ""))
        canonical_candidates = [
            concept.get("canonical_name"),
            concept.get("canonical_name_clean"),
            concept.get("name"),
            concept.get("title"),
        ]
        canonical_terms = [
            _safe_normalize_for_matching(str(v or ""))
            for v in canonical_candidates
            if str(v or "").strip()
        ]
        aliases = _as_list(concept.get("aliases"))
        alias_terms: List[str] = []
        seen_alias: Set[str] = set()
        for a in aliases[:200]:
            an = _safe_normalize_for_matching(str(a))
            if not an or len(an) < 2 or an in seen_alias:
                continue
            seen_alias.add(an)
            alias_terms.append(an)
            alias_freq[an] = alias_freq.get(an, 0) + 1

        entries.append(
            {
                "key": str(concept_key or ""),
                "display_name": display,
                "display_n": display_n,
                "key_n": key_n,
                "canonical_terms": canonical_terms,
                "alias_terms": alias_terms,
                "aliases": aliases[:20],
            }
        )

    _RAG_DIRECT_TEST_INDEX_CACHE = (entries, alias_freq)
    return _RAG_DIRECT_TEST_INDEX_CACHE


def _collect_direct_test_matches(query_norm: str, max_matches: int = 8) -> List[Dict[str, Any]]:
    q = _safe_normalize_for_matching(query_norm or "")
    if not q:
        return []

    direct_entries, alias_freq = _build_direct_test_light_index()
    if not direct_entries:
        return []

    q_tokens = [t for t in q.split() if t]
    q_token_set = set(q_tokens[:12])
    query_has_code = bool(_extract_lab_code_tokens(query_norm)) or any(_is_code_like_token(t) for t in q_tokens)
    matches: List[Dict[str, Any]] = []

    for entry in direct_entries:
        concept_key = entry["key"]
        display = entry["display_name"]
        display_n = entry["display_n"]
        key_n = entry["key_n"]
        canonical_terms = entry["canonical_terms"]
        alias_terms = entry["alias_terms"]
        aliases = entry["aliases"]

        best_score = 0.0
        match_type = ""
        matched_terms: List[str] = []

        def _try_update(score: float, reason: str, term: str) -> None:
            nonlocal best_score, match_type
            if score > best_score:
                best_score = score
                match_type = reason
            if term and term not in matched_terms:
                matched_terms.append(term)

        for candidate in [display_n, key_n, *canonical_terms]:
            if not candidate:
                continue
            if candidate == q:
                _try_update(0.98, "exact_display_or_canonical", candidate)
            elif len(q) >= 3 and q in candidate:
                _try_update(0.90, "display_or_canonical_overlap", candidate)
            elif len(candidate) >= 3 and candidate in q:
                _try_update(0.90, "display_or_canonical_overlap", candidate)

            if query_has_code:
                c_tokens = candidate.split()
                for ct in c_tokens:
                    if _is_code_like_token(ct) and ct == q:
                        _try_update(0.93, "abbreviation_or_code", ct)
                    elif _is_code_like_token(ct) and ct in q_token_set:
                        _try_update(0.90, "abbreviation_or_code", ct)

        for alias in alias_terms:
            if alias == q:
                freq = alias_freq.get(alias, 1)
                if _is_code_like_token(alias) and freq > 3:
                    _try_update(0.78, "ambiguous_exact_alias", alias)
                else:
                    _try_update(1.0, "exact_alias", alias)
                continue
            if not _is_code_like_token(q):
                if len(q) >= 3 and q in alias:
                    _try_update(0.92, "strong_contains", alias)
                elif len(alias) >= 3 and alias in q:
                    _try_update(0.90, "strong_contains", alias)
                else:
                    a_tokens = set(alias.split())
                    if q_token_set and a_tokens and (q_token_set & a_tokens):
                        overlap = len(q_token_set & a_tokens) / max(1, min(len(q_token_set), len(a_tokens)))
                        if overlap >= 0.67:
                            _try_update(0.84 + min(0.08, overlap * 0.1), "token_overlap", alias)

            if query_has_code:
                for at in alias.split():
                    if not _is_code_like_token(at):
                        continue
                    freq = alias_freq.get(at, 1)
                    if at == q:
                        if freq > 3:
                            _try_update(0.76, "ambiguous_code_alias", at)
                        else:
                            _try_update(0.93, "abbreviation_or_code", at)
                    elif at in q_token_set:
                        if freq > 3:
                            _try_update(0.76, "ambiguous_code_alias", at)
                        else:
                            _try_update(0.90, "abbreviation_or_code", at)

        if best_score < 0.8:
            continue

        matches.append(
            {
                "key": str(concept_key or ""),
                "display_name": display,
                "score": best_score,
                "match_type": match_type,
                "matched_terms": matched_terms[:6],
                "aliases": aliases[:20],
            }
        )

    matches.sort(key=lambda x: x["score"], reverse=True)
    return matches[:max_matches]


def _is_direct_entity_query(text_norm: str) -> bool:
    q = _safe_normalize_for_matching(text_norm or "")
    if not q:
        return False

    q_tokens = [t for t in q.split() if t]
    if not q_tokens:
        return False

    token_count = len(q_tokens)
    short_or_medium = token_count <= 6 and len(q) <= 80
    if not short_or_medium:
        return False

    broad_markers = {
        _safe_normalize_for_matching(x)
        for x in (
            "ما هي",
            "تحاليل",
            "تحليلات",
            "اعراض",
            "أعراض",
            "اسباب",
            "أسباب",
            "ماسبب",
            "why",
            "symptoms",
            "causes",
            "benefits",
            "preparation",
        )
    }
    broad_hits = sum(1 for t in q_tokens if t in broad_markers)

    has_code_like = bool(_extract_lab_code_tokens(text_norm or "")) or any(
        _is_code_like_token(t) for t in q_tokens
    )
    direct_matches = _collect_direct_test_matches(q, max_matches=3)
    top_score = float(direct_matches[0]["score"]) if direct_matches else 0.0
    top_type = str(direct_matches[0].get("match_type") or "") if direct_matches else ""

    if has_code_like and top_score >= 0.84:
        return True
    if has_code_like and token_count <= 3:
        return True
    if top_score >= 0.97:
        return True
    if top_score >= 0.9 and broad_hits <= 1:
        return True
    if top_type == "exact_alias" and top_score >= 0.9:
        return True

    looks_like_title = (_contains_arabic(q) and token_count <= 4 and broad_hits == 0) or (
        not _contains_arabic(q) and token_count <= 3
    )
    if looks_like_title and top_score >= 0.86:
        return True

    return False


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

    direct_query_norm = _safe_normalize_for_matching(_extract_search_terms(query) or query)
    direct_test_matches = _collect_direct_test_matches(direct_query_norm, max_matches=8)
    is_direct_entity = _is_direct_entity_query(direct_query_norm)
    print(
        "RAG_DIRECT_ENTITY_DEBUG",
        {
            "query": str(query or "").encode("unicode_escape").decode("ascii"),
            "is_direct_entity": is_direct_entity,
            "direct_matches": [
                {
                    "key": str(m.get("key") or "").encode("unicode_escape").decode("ascii"),
                    "display_name": str(m.get("display_name") or "").encode("unicode_escape").decode("ascii"),
                    "score": round(float(m.get("score") or 0.0), 4),
                    "match_type": str(m.get("match_type") or ""),
                }
                for m in direct_test_matches[:5]
            ],
        },
    )

    direct_exact_alias_terms: Set[str] = set()
    direct_display_terms: Set[str] = set()
    direct_code_terms: Set[str] = set()
    query_code_terms: Set[str] = set()
    for tk in _extract_lab_code_tokens(query):
        tk_n = _safe_normalize_for_matching(tk)
        if tk_n:
            query_code_terms.add(tk_n)
    for tk in direct_query_norm.split():
        if _is_code_like_token(tk):
            query_code_terms.add(tk)
    for m in direct_test_matches:
        m_score = float(m.get("score") or 0.0)
        m_display = _safe_normalize_for_matching(m.get("display_name") or "")
        m_key = _safe_normalize_for_matching(m.get("key") or "")
        if m_display and m_score >= 0.92:
            direct_display_terms.add(m_display)
        if m_key and m_score >= 0.92:
            direct_display_terms.add(m_key)
        m_type = str(m.get("match_type") or "")
        for mt in m.get("matched_terms", []):
            mt_n = _safe_normalize_for_matching(mt)
            if not mt_n:
                continue
            if m_type == "exact_alias" and mt_n == direct_query_norm:
                direct_exact_alias_terms.add(mt_n)
            if m_type in {"exact_display_or_canonical", "display_or_canonical_overlap"} and m_score >= 0.9:
                direct_display_terms.add(mt_n)
            if (
                m_type == "abbreviation_or_code"
                or (_is_code_like_token(mt_n) and (mt_n == direct_query_norm or mt_n in query_code_terms))
            ):
                direct_code_terms.add(mt_n)

    retrieval_pool = max(max_results, 5)
    if is_direct_entity:
        retrieval_pool = max(retrieval_pool * 6, 24)
    else:
        retrieval_pool = max(retrieval_pool * 3, 12)

    detected_tokens = _extract_lab_code_tokens(concept_expanded_query)
    structured_results = _structured_code_match(concept_expanded_query, tests, max_results=retrieval_pool)
    lexical_results = _lexical_retrieve(
        concept_expanded_query,
        tests,
        max_results=retrieval_pool,
        min_score=LEXICAL_MIN_SCORE,
    )
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

    direct_results: List[Dict[str, Any]] = []
    if direct_test_matches:
        for t in tests:
            name_ar = _safe_normalize_for_matching(t.get("analysis_name_ar") or "")
            name_en = _safe_normalize_for_matching(t.get("analysis_name_en") or "")
            canonical_clean = _safe_normalize_for_matching(t.get("canonical_name_clean") or "")
            test_names = [name_ar, name_en, canonical_clean]
            direct_score = 0.0
            if direct_exact_alias_terms and any(n and n in direct_exact_alias_terms for n in test_names):
                direct_score = max(direct_score, 0.99)
            if direct_display_terms and any(
                n and any((n == dt) or (len(dt) >= 3 and dt in n) or (len(n) >= 3 and n in dt) for dt in direct_display_terms)
                for n in test_names
            ):
                direct_score = max(direct_score, 0.95)
            if direct_code_terms and any(
                n and any((n == code) or (len(code) >= 2 and code in n) for code in direct_code_terms)
                for n in test_names
            ):
                direct_score = max(direct_score, 0.9)
            if query_code_terms:
                token_space = set(f"{name_ar} {name_en} {canonical_clean}".split())
                if token_space and any(code in token_space for code in query_code_terms):
                    direct_score = max(direct_score, 0.9)
            if direct_score > 0:
                direct_results.append({"test": t, "score": direct_score, "source": "direct"})
        direct_results.sort(key=lambda x: x["score"], reverse=True)
        direct_results = direct_results[:retrieval_pool]

    lexical_results = structured_results + lexical_results + direct_results
    lexical_has_sufficient = any(
        (r.get("source") in {"lexical", "structured", "direct"}) and float(r.get("score") or 0.0) >= lex_min
        for r in lexical_results
    )

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
        direct_rank = 0
        direct_confidence = 0.0
        # Small boost when expanded query directly includes canonical test name fields.
        name_ar = _safe_normalize_for_matching(t.get("analysis_name_ar") or "")
        name_en = _safe_normalize_for_matching(t.get("analysis_name_en") or "")
        expanded_norm = _safe_normalize_for_matching(concept_expanded_query)
        canonical_clean = _safe_normalize_for_matching(t.get("canonical_name_clean") or "")
        test_names = [name_ar, name_en, canonical_clean]
        if (
            (name_ar and name_ar in expanded_norm)
            or (name_en and name_en in expanded_norm)
            or (canonical_clean and canonical_clean in expanded_norm)
        ):
            score = min(1.0, score + 0.05)
        if _related_test_match([name_ar, name_en, canonical_clean], concept_related_tests):
            score = min(1.0, score + 0.05)
        if is_direct_entity and direct_test_matches:
            if direct_exact_alias_terms and any(n and n in direct_exact_alias_terms for n in test_names):
                score = min(1.0, score + 0.12)
                direct_rank = max(direct_rank, 3)
                direct_confidence = max(direct_confidence, 1.0)
            elif direct_display_terms and any(
                n and any((n == dt) or (len(dt) >= 3 and dt in n) or (len(n) >= 3 and n in dt) for dt in direct_display_terms)
                for n in test_names
            ):
                score = min(1.0, score + 0.10)
                direct_rank = max(direct_rank, 2)
                direct_confidence = max(direct_confidence, 0.9)
            elif direct_code_terms and any(
                n and any((n == code) or (len(code) >= 2 and code in n) for code in direct_code_terms)
                for n in test_names
            ):
                score = min(1.0, score + 0.08)
                direct_rank = max(direct_rank, 1)
                direct_confidence = max(direct_confidence, 0.8)
            elif query_code_terms:
                token_space = set(f"{name_ar} {name_en} {canonical_clean}".split())
                if token_space and any(code in token_space for code in query_code_terms):
                    score = min(1.0, score + 0.08)
                    direct_rank = max(direct_rank, 1)
                    direct_confidence = max(direct_confidence, 0.8)
            else:
                # Keep direct-entity ranking focused on specific test mappings.
                score = max(0.0, score - 0.03)
        chunk_text = _safe_normalize_for_matching(t.get("__chunk_text") or _build_document_text(t))
        if chunk_text:
            if strong_concept_aliases and any(a in chunk_text for a in strong_concept_aliases):
                score = min(1.0, score + 0.05)
            if asks_preparation and prep_signals and any(s in chunk_text for s in prep_signals):
                score = min(1.0, score + 0.05)
            if asks_symptoms and symptom_signals and any(s in chunk_text for s in symptom_signals):
                score = min(1.0, score + 0.05)
        src = r.get("source", "lexical")
        if (
            k not in best_by_key
            or score > best_by_key[k]["score"]
            or (
                is_direct_entity
                and direct_rank > int(best_by_key[k].get("direct_rank") or 0)
                and score >= float(best_by_key[k]["score"]) - 0.02
            )
        ):
            best_by_key[k] = {
                "test": t,
                "score": score,
                "source": src,
                "direct_rank": direct_rank,
                "direct_confidence": direct_confidence,
            }

    # Include lexical results passing lexical threshold (or explicit similarity threshold).
    merged = [
        v for v in best_by_key.values()
        if (v["score"] >= similarity_threshold)
        or (v.get("source") == "lexical" and v["score"] >= lex_min)
    ]
    if is_direct_entity:
        merged.sort(
            key=lambda x: (
                int(x.get("direct_rank") or 0),
                float(x.get("direct_confidence") or 0.0),
                float(x["score"]),
            ),
            reverse=True,
        )
    else:
        merged.sort(key=lambda x: x["score"], reverse=True)
    merged = merged[:max_results]

    has_sufficient = any(
        (r.get("source") in {"lexical", "structured", "direct"} and r["score"] >= lex_min)
        or (r["score"] >= similarity_threshold)
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
    
    query_norm = _safe_normalize_for_matching(user_message)
    asks_preparation = _is_preparation_query(user_message)
    asks_symptoms = _is_symptom_query(user_message)
    asks_price = include_prices and bool(
        any(k in query_norm for k in ("سعر", "بكم", "تكلفة", "تكلفه", "price", "cost"))
    )

    max_context_results = min(2 if asks_symptoms else 1, max_tests)
    compact_parts: List[str] = []

    for r in above_threshold[:max_context_results]:
        test = r["test"]
        name_ar = str(test.get("analysis_name_ar") or "").strip()
        name_en = str(test.get("analysis_name_en") or "").strip()
        name = name_ar or name_en or "تحليل غير محدد"

        desc = str(test.get("description") or "").strip()
        prep = str(test.get("preparation") or "").strip()
        symptoms = str(test.get("symptoms") or "").strip()
        complementary = str(test.get("complementary_tests") or "").strip()
        price = test.get("price")

        lines: List[str] = [f"اسم التحليل: {name}"]

        if asks_price:
            if price is not None:
                lines.append(f"السعر: {price}")
            else:
                lines.append("السعر: غير متوفر حالياً")
        elif asks_preparation:
            if prep:
                lines.append(f"التحضير: {prep}")
            elif desc:
                lines.append(f"الفائدة: {desc}")
        elif asks_symptoms:
            if symptoms:
                lines.append(f"الأعراض المرتبطة: {symptoms}")
            if complementary:
                lines.append(f"تحاليل مكملة: {complementary}")
            if not symptoms and desc:
                lines.append(f"الفائدة: {desc}")
        else:
            if desc:
                lines.append(f"الفائدة: {desc}")
            if prep and any(k in query_norm for k in ("صيام", "تحضير", "قبل التحليل", "before test")):
                lines.append(f"التحضير: {prep}")

        compact_parts.append("\n".join(lines))

    context_str = "\n\n".join([p for p in compact_parts if p.strip()])
    if not context_str:
        return "", False
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


def get_site_fallback_context(query: str, max_chunks: int = 3) -> str:
    query_norm = _safe_normalize_for_matching(_extract_search_terms(query) or query or "")
    if not query_norm:
        return ""
    chunks = load_site_knowledge_chunks()
    if not chunks:
        return ""

    q_tokens = set(query_norm.split())
    use_arabic_fast = _contains_arabic(query_norm)
    SequenceMatcher = None
    if not use_arabic_fast:
        try:
            from difflib import SequenceMatcher as _SM
            SequenceMatcher = _SM
        except Exception:
            SequenceMatcher = None

    scored: List[Tuple[float, str]] = []
    for ch in chunks:
        if not isinstance(ch, dict):
            continue
        text_raw = str(ch.get("text") or "").strip()
        if not text_raw:
            continue
        text_norm = _safe_normalize_for_matching(text_raw[:2000])
        if not text_norm:
            continue

        score = 0.0
        if query_norm == text_norm:
            score = 1.0
        elif len(query_norm) >= 3 and query_norm in text_norm:
            score = 0.95
        elif len(text_norm) >= 3 and text_norm in query_norm:
            score = 0.9
        else:
            t_tokens = set(text_norm.split())
            if q_tokens and t_tokens:
                overlap = len(q_tokens & t_tokens) / max(1, len(q_tokens))
                if overlap >= 0.35:
                    score = max(score, 0.65 + min(0.2, overlap * 0.3))
            if score < 0.62 and SequenceMatcher is not None and len(query_norm) >= 4:
                ratio = SequenceMatcher(None, query_norm, text_norm[:260]).ratio()
                if ratio >= 0.72:
                    score = max(score, 0.58 + ratio * 0.3)
        if score >= 0.62:
            scored.append((score, text_raw))

    if not scored:
        return ""

    scored.sort(key=lambda x: x[0], reverse=True)
    top = [t for _, t in scored[:max(1, max_chunks)]]
    print("PATH=runtime_site_fallback")
    return "\n" + ("\n" + "-" * 50 + "\n").join(top)


if __name__ == "__main__":
    chunks = load_runtime_chunks_jsonl(TESTS_CHUNKS_PATH)
    print("Loaded runtime chunks:", len(chunks))
