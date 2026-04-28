
"""Deterministic symptom-to-tests suggestion engine from unified tests dataset."""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.services.runtime.text_normalizer import normalize_for_match

TESTS_JSONL_PATH = Path("app/data/runtime/rag/tests_clean.jsonl")
logger = logging.getLogger(__name__)

_CLARIFICATION_MESSAGE = "إذا ممكن تشرح لي الأعراض اللي تحس فيها بشكل أوضح، عشان أقدر أعطيك معلومات أدق."
_GENERIC_ONLY_TERMS = {
    normalize_for_match("\u0639\u0646\u062f\u064a"),
    normalize_for_match("\u0627\u062d\u0633"),
    normalize_for_match("\u0623\u062d\u0633"),
    normalize_for_match("\u0627\u0639\u0627\u0646\u064a"),
    normalize_for_match("\u0623\u0639\u0627\u0646\u064a"),
    normalize_for_match("\u0627\u0639\u0631\u0627\u0636"),
    normalize_for_match("\u0623\u0639\u0631\u0627\u0636"),
    normalize_for_match("\u0641\u064a"),
    normalize_for_match("\u0645\u0646"),
    normalize_for_match("\u0645\u0639"),
}
_SYMPTOM_STOPWORDS = {
    normalize_for_match("عندي"),
    normalize_for_match("عند"),
    normalize_for_match("ايش"),
    normalize_for_match("وش"),
    normalize_for_match("اللي"),
    normalize_for_match("تنصحني"),
    normalize_for_match("به"),
    normalize_for_match("في"),
    normalize_for_match("من"),
    normalize_for_match("مع"),
    normalize_for_match("عن"),
    normalize_for_match("تحليل"),
    normalize_for_match("تحاليل"),
    normalize_for_match("فحص"),
    normalize_for_match("نتيجة"),
}
_SYMPTOM_QUERY_HINTS = tuple(
    normalize_for_match(v)
    for v in (
        "\u062a\u0639\u0628",
        "\u0627\u0631\u0647\u0627\u0642",
        "\u062f\u0648\u062e\u0629",
        "\u0635\u062f\u0627\u0639",
        "\u062d\u0645\u0649",
        "\u062d\u0631\u0627\u0631\u0629",
        "\u0643\u062d\u0629",
        "\u0627\u0644\u062a\u0647\u0627\u0628 \u062d\u0644\u0642",
        "\u0627\u0644\u0645 \u0628\u0637\u0646",
        "\u0645\u063a\u0635",
        "\u063a\u062b\u064a\u0627\u0646",
        "\u062a\u0633\u0627\u0642\u0637 \u0627\u0644\u0634\u0639\u0631",
        "\u062e\u0641\u0642\u0627\u0646",
        "\u0641\u0642\u0631 \u062f\u0645",
        "\u0646\u0642\u0635 \u0641\u064a\u062a\u0627\u0645\u064a\u0646",
        "\u062e\u0645\u0648\u0644",
        "\u0636\u0639\u0641 \u0639\u0627\u0645",
    )
    if normalize_for_match(v)
)


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _norm(value: Any) -> str:
    return normalize_for_match(_safe_str(value))


def _as_list_of_str(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_safe_str(v) for v in value if _safe_str(v)]
    text = _safe_str(value)
    return [text] if text else []


def _token_overlap_ratio(query_norm: str, term_norm: str) -> float:
    q_tokens = {t for t in query_norm.split() if t}
    t_tokens = {t for t in term_norm.split() if t}
    if not q_tokens or not t_tokens:
        return 0.0
    inter = q_tokens.intersection(t_tokens)
    denom = max(len(q_tokens), len(t_tokens))
    if denom <= 0:
        return 0.0
    return float(len(inter) / denom)


def _split_query_chunks(query_norm: str) -> list[str]:
    parts: list[str] = [query_norm]
    for sep in (" \u0648 ", "\u060c", ",", " \u0645\u0639 "):
        next_parts: list[str] = []
        for part in parts:
            next_parts.extend([p.strip() for p in part.split(sep) if p.strip()])
        parts = next_parts or parts
    return [p for p in parts if p]


def _extract_symptom_tokens(text_norm: str) -> set[str]:
    tokens = {t for t in text_norm.split() if t}
    out: set[str] = set()
    for token in tokens:
        t = token
        # Normalize Arabic conjunction prefix for compact user writing:
        # "واسهال" -> "اسهال"
        if t.startswith("و") and len(t) > 2:
            t = t[1:]
        if len(t) > 1 and t not in _SYMPTOM_STOPWORDS:
            out.add(t)
    return out


@lru_cache(maxsize=1)
def load_symptoms_mappings() -> list[dict[str, Any]]:
    """Build per-test symptom index directly from unified tests_clean.jsonl."""
    if not TESTS_JSONL_PATH.exists():
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

            test_name = _safe_str(
                obj.get("canonical_name_ar")
                or obj.get("test_name_ar")
                or obj.get("title")
                or obj.get("h1")
            )
            if not test_name:
                continue

            symptoms = _as_list_of_str(obj.get("symptoms"))
            if not symptoms:
                symptoms = _as_list_of_str(obj.get("excel_symptoms"))
            if not symptoms:
                continue

            symptom_norm_list: list[str] = []
            symptom_tokens: set[str] = set()
            for symptom in symptoms:
                symptom_norm = _norm(symptom)
                if not symptom_norm:
                    continue
                symptom_norm_list.append(symptom_norm)
                symptom_tokens.update(_extract_symptom_tokens(symptom_norm))

            if not symptom_norm_list and not symptom_tokens:
                continue

            rows.append(
                {
                    "test_name": test_name,
                    "symptoms_norm": symptom_norm_list,
                    "symptom_tokens": symptom_tokens,
                }
            )
    return rows


def _match_symptom_record(query_norm: str, record: dict[str, Any]) -> float:
    if not query_norm:
        return 0.0
    query_tokens = _extract_symptom_tokens(query_norm)
    if not query_tokens:
        return 0.0

    symptom_tokens = set(record.get("symptom_tokens") or set())
    symptom_phrases = list(record.get("symptoms_norm") or [])

    overlap = query_tokens.intersection(symptom_tokens)
    phrase_hits = [p for p in symptom_phrases if p and p in query_norm]
    if not overlap and not phrase_hits:
        return 0.0

    overlap_count = len(overlap)
    coverage = overlap_count / max(1, len(query_tokens))
    score = float(overlap_count) + (0.25 * len(phrase_hits)) + (0.10 * coverage)
    logger.debug(
        "symptoms_detector score | query=%s | test=%s | overlap=%s | phrase_hits=%s | score=%.3f",
        query_norm,
        _safe_str(record.get("test_name")),
        overlap_count,
        len(phrase_hits),
        score,
    )
    return score


def _looks_like_weak_symptom_query(query_norm: str) -> bool:
    tokens = [t for t in query_norm.split() if t]
    if not tokens:
        return False
    if all(t in _GENERIC_ONLY_TERMS for t in tokens):
        return True
    return any(h in query_norm for h in _SYMPTOM_QUERY_HINTS) or any(t in _GENERIC_ONLY_TERMS for t in tokens)


def _rank_merged_tests_and_packages(
    matches: list[tuple[float, dict[str, Any]]],
) -> tuple[list[str], list[str]]:
    """Rank tests by overlap score and return top 3-5 test names."""
    test_scores: dict[str, float] = {}
    test_labels: dict[str, str] = {}

    for match_score, record in matches:
        test_name = _safe_str(record.get("test_name"))
        key = _norm(test_name)
        if not test_name or not key:
            continue
        test_scores[key] = test_scores.get(key, 0.0) + float(match_score)
        test_labels.setdefault(key, test_name)

    ranked_tests = sorted(test_scores.keys(), key=lambda k: (-test_scores.get(k, 0.0), k))
    top_tests = [test_labels[k] for k in ranked_tests[:5] if test_labels.get(k)]
    return top_tests, []


def handle_symptoms_query(query: str) -> dict[str, Any] | None:
    """Return deterministic symptom mapping result if a symptom is matched."""
    query_norm = _norm(query)
    if not query_norm:
        return None

    scored_records: list[tuple[float, dict[str, Any]]] = []
    for record in load_symptoms_mappings():
        score = _match_symptom_record(query_norm, record)
        if score > 0.0:
            scored_records.append((score, record))

    if not scored_records:
        return None

    scored_records.sort(key=lambda x: x[0], reverse=True)
    strong_matches = [(s, r) for s, r in scored_records if s >= 1.0]

    if not strong_matches:
        logger.debug(
            "symptoms_detector weak_match | query=%s | top_score=%.3f | reason=low_confidence",
            query_norm,
            float(scored_records[0][0]),
        )
        return None

    merged_tests, merged_packages = _rank_merged_tests_and_packages(strong_matches)

    if not merged_tests and not merged_packages:
        return {
            "type": "symptom_clarification",
            "symptoms": [],
            "tests": [],
            "packages": [],
            "answer": _CLARIFICATION_MESSAGE,
        }

    return {
        "type": "symptom_match",
        "symptoms": sorted(_extract_symptom_tokens(query_norm)),
        "tests": merged_tests,
        "packages": merged_packages,
    }
