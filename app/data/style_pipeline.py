"""
Style Retrieval Pipeline
========================
Loads style examples and performs cosine-similarity retrieval.
"""

from __future__ import annotations

import json
import logging
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Optional

from app.core.config import settings
from app.services.embeddings_service import get_embedding

logger = logging.getLogger(__name__)

STYLE_EMBEDDINGS_PATH = Path(__file__).resolve().parent / "style_embeddings.json"
STYLE_PAIRS_PATH = Path(__file__).resolve().parent / "style_pairs.jsonl"


def _norm(v: List[float]) -> float:
    return sum(x * x for x in v) ** 0.5


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    na = _norm(a)
    nb = _norm(b)
    if na == 0 or nb == 0:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (na * nb)


def _truncate(value: str, max_chars: int) -> str:
    text = (value or "").strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."


def _normalize_text(value: str) -> str:
    text = (value or "").strip().lower()
    if not text:
        return ""
    text = re.sub(r"[\u064B-\u065F\u0670]", "", text)
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    text = text.replace("ى", "ي").replace("ؤ", "و").replace("ئ", "ي")
    text = re.sub(r"[^\w\s\u0600-\u06FF]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _token_overlap_score(a: str, b: str) -> float:
    ta = set(_normalize_text(a).split())
    tb = set(_normalize_text(b).split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(1, len(ta))


def _lexical_similarity(query: str, customer: str, agent: str) -> float:
    qn = _normalize_text(query)
    combined = _normalize_text(f"{customer} {agent}")
    if not qn or not combined:
        return 0.0
    overlap = _token_overlap_score(qn, combined)
    ratio = SequenceMatcher(None, qn, combined).ratio()
    return max(overlap, ratio)


def _load_pairs_from_jsonl(path: Path) -> List[Dict]:
    if not path.exists():
        return []
    pairs: List[Dict] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                customer = (rec.get("customer") or "").strip()
                agent = (rec.get("agent") or "").strip()
                if customer and agent:
                    pairs.append(rec)
    except Exception as exc:
        logger.warning("Failed to load style pairs jsonl (%s): %s", path, exc)
    return pairs


def _format_examples(pairs: List[Dict], indices: List[int]) -> List[str]:
    max_chars = settings.STYLE_MAX_CHARS_PER_EXAMPLE
    out: List[str] = []
    for idx in indices:
        pair = pairs[idx]
        customer = _truncate(pair.get("customer", ""), max_chars)
        agent = _truncate(pair.get("agent", ""), max_chars)
        out.append(f"Customer: {customer}\nAgent: {agent}")
    return out


def _search_lexical_examples(query: str, pairs: List[Dict], top_k: int) -> List[str]:
    if not query or not pairs or not getattr(settings, "STYLE_FALLBACK_LEXICAL", True):
        return []
    threshold = getattr(settings, "STYLE_FALLBACK_MIN_SCORE", 0.25)
    scored = []
    all_scored = []
    for i, pair in enumerate(pairs):
        score = _lexical_similarity(query, pair.get("customer", ""), pair.get("agent", ""))
        all_scored.append((i, score))
        if score >= threshold:
            scored.append((i, score))

    ranked = scored if scored else all_scored
    if not ranked:
        return []
    ranked.sort(key=lambda x: x[1], reverse=True)
    selected = [i for i, _ in ranked[: max(1, top_k)]]
    return _format_examples(pairs, selected)


def load_style_index(path: Optional[str] = None) -> Dict:
    target = Path(path) if path else STYLE_EMBEDDINGS_PATH
    if not target.exists():
        return {"pairs": _load_pairs_from_jsonl(STYLE_PAIRS_PATH), "pair_embeddings": []}
    try:
        with target.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        logger.warning("Failed to load style index (%s): %s", target, exc)
        return {"pairs": [], "pair_embeddings": []}

    pairs = data.get("pairs") or []
    vectors = data.get("pair_embeddings") or []
    if not pairs:
        pairs = _load_pairs_from_jsonl(STYLE_PAIRS_PATH)
    if vectors and len(pairs) != len(vectors):
        logger.warning("Style index mismatch: pairs=%s vectors=%s", len(pairs), len(vectors))
        size = min(len(pairs), len(vectors))
        pairs = pairs[:size]
        vectors = vectors[:size]
    return {"pairs": pairs, "pair_embeddings": vectors}


def search_style_examples(query: str, top_k: int = 3) -> List[str]:
    index = load_style_index()
    pairs = index.get("pairs") or []
    vectors = index.get("pair_embeddings") or []
    if not query or not pairs:
        return []

    # Robust fallback trigger:
    # - any empty stored vector
    # - missing vectors
    use_lexical = (not vectors) or any((not v) or len(v) == 0 for v in vectors)

    q_emb: List[float] = []
    if not use_lexical:
        q_emb = get_embedding(query)
        if not q_emb:
            use_lexical = True

    if use_lexical:
        return _search_lexical_examples(query, pairs, top_k)

    scored = []
    for i, vec in enumerate(vectors):
        if not vec:
            continue
        score = _cosine_similarity(q_emb, vec)
        if score >= settings.STYLE_MIN_SCORE:
            scored.append((i, score))
    scored.sort(key=lambda x: x[1], reverse=True)

    selected = [idx for idx, _score in scored[: max(1, top_k)]]
    if selected:
        return _format_examples(pairs, selected)
    return _search_lexical_examples(query, pairs, top_k)
