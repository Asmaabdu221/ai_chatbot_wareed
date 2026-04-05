"""Deterministic symptom-to-tests/package suggestion engine."""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.services.runtime.text_normalizer import normalize_arabic

SYMPTOMS_MAPPING_JSONL_PATH = Path("app/data/runtime/rag/symptoms_mapping.jsonl")
logger = logging.getLogger(__name__)


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _norm(value: Any) -> str:
    return normalize_arabic(_safe_str(value))


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


@lru_cache(maxsize=1)
def load_symptoms_mappings() -> list[dict[str, Any]]:
    if not SYMPTOMS_MAPPING_JSONL_PATH.exists():
        return []

    rows: list[dict[str, Any]] = []
    with SYMPTOMS_MAPPING_JSONL_PATH.open("r", encoding="utf-8") as f:
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

            symptom = _safe_str(obj.get("symptom"))
            aliases = _as_list_of_str(obj.get("aliases"))
            tests = _as_list_of_str(obj.get("suggested_tests"))
            packages = _as_list_of_str(obj.get("suggested_packages"))
            if not symptom or (not tests and not packages):
                continue

            item = {
                "symptom": symptom,
                "aliases": aliases,
                "suggested_tests": tests,
                "suggested_packages": packages,
                "symptom_norm": _norm(symptom),
                "aliases_norm": [_norm(a) for a in aliases if _norm(a)],
            }
            rows.append(item)
    return rows


def _match_symptom_record(query_norm: str, record: dict[str, Any]) -> float:
    if not query_norm:
        return 0.0
    terms = [_safe_str(record.get("symptom_norm"))] + list(record.get("aliases_norm") or [])
    symptom_norm = _safe_str(record.get("symptom_norm"))

    query_tokens = [t for t in query_norm.split() if t]
    generic_short_tokens = {"عندي", "فيه", "في", "مع", "من", "احس", "أحس"}
    short_ambiguous = len(query_tokens) <= 2 and all(t in generic_short_tokens for t in query_tokens) if query_tokens else False

    best = 0.0
    best_details = ""
    for term in terms:
        if not term:
            continue

        score = 0.0
        details: list[str] = []

        # Exact symptom/alias match stays strongest.
        if query_norm == term:
            score += 1.0
            details.append("exact")
        else:
            # Boundary containment gets stronger confidence than loose containment.
            padded_q = f" {query_norm} "
            padded_t = f" {term} "
            if padded_t in padded_q:
                score += 0.92
                details.append("boundary_contains")
            elif term in query_norm:
                score += 0.85
                details.append("contains")
            elif len(query_norm) >= 4 and query_norm in term:
                score += 0.70
                details.append("reverse_contains")

            # Token overlap as deterministic lexical signal.
            overlap = _token_overlap_ratio(query_norm, term)
            if overlap > 0:
                overlap_boost = min(0.25, overlap * 0.25)
                score += overlap_boost
                details.append(f"token_overlap={overlap:.2f}")

        # Ambiguity penalty for very short generic queries.
        if short_ambiguous:
            score -= 0.20
            details.append("short_ambiguous_penalty")

        score = max(0.0, min(1.0, score))
        if score > best:
            best = score
            best_details = ",".join(details)

    logger.debug(
        "symptoms_detector score | query=%s | symptom=%s | score=%.3f | details=%s",
        query_norm,
        symptom_norm,
        best,
        best_details,
    )
    return best


def handle_symptoms_query(query: str) -> dict[str, Any] | None:
    """Return deterministic symptom mapping result if a symptom is matched."""
    query_norm = _norm(query)
    if not query_norm:
        return None

    matched_records: list[dict[str, Any]] = []
    for record in load_symptoms_mappings():
        score = _match_symptom_record(query_norm, record)
        if score >= 0.75:
            matched_records.append(record)

    if not matched_records:
        return None

    symptoms: list[str] = []
    tests_seen: set[str] = set()
    packages_seen: set[str] = set()
    merged_tests: list[str] = []
    merged_packages: list[str] = []

    for record in matched_records:
        symptom = _safe_str(record.get("symptom"))
        if symptom and symptom not in symptoms:
            symptoms.append(symptom)

        for test_name in list(record.get("suggested_tests") or []):
            value = _safe_str(test_name)
            key = _norm(value)
            if value and key not in tests_seen:
                tests_seen.add(key)
                merged_tests.append(value)

        for package_name in list(record.get("suggested_packages") or []):
            value = _safe_str(package_name)
            key = _norm(value)
            if value and key not in packages_seen:
                packages_seen.add(key)
                merged_packages.append(value)

    return {
        "type": "symptom_match",
        "symptoms": symptoms,
        "tests": merged_tests,
        "packages": merged_packages,
    }
