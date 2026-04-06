
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

_CLARIFICATION_MESSAGE = (
    "\u0648\u0635\u0651\u0641 \u0627\u0644\u0639\u0631\u0636 \u0627\u0644\u0631\u0626\u064a\u0633\u064a \u0628\u0634\u0643\u0644 \u0623\u0648\u0636\u062d "
    "(\u0645\u062b\u0644: \u0635\u062f\u0627\u0639 \u0645\u0633\u062a\u0645\u0631\u060c \u062d\u0631\u0627\u0631\u0629 \u0645\u0639 \u0643\u062d\u0629\u060c "
    "\u0623\u0644\u0645 \u0628\u0637\u0646 \u0645\u0639 \u063a\u062b\u064a\u0627\u0646) \u0648\u0623\u0646\u0627 \u0623\u0642\u062a\u0631\u062d \u0644\u0643 "
    "\u062a\u062d\u0627\u0644\u064a\u0644 \u0623\u062f\u0642."
)
_GENERIC_ONLY_TERMS = {
    normalize_arabic("\u0639\u0646\u062f\u064a"),
    normalize_arabic("\u0627\u062d\u0633"),
    normalize_arabic("\u0623\u062d\u0633"),
    normalize_arabic("\u0627\u0639\u0627\u0646\u064a"),
    normalize_arabic("\u0623\u0639\u0627\u0646\u064a"),
    normalize_arabic("\u0627\u0639\u0631\u0627\u0636"),
    normalize_arabic("\u0623\u0639\u0631\u0627\u0636"),
    normalize_arabic("\u0641\u064a"),
    normalize_arabic("\u0645\u0646"),
    normalize_arabic("\u0645\u0639"),
}
_SYMPTOM_QUERY_HINTS = tuple(
    normalize_arabic(v)
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
    if normalize_arabic(v)
)


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


def _split_query_chunks(query_norm: str) -> list[str]:
    parts: list[str] = [query_norm]
    for sep in (" \u0648 ", "\u060c", ",", " \u0645\u0639 "):
        next_parts: list[str] = []
        for part in parts:
            next_parts.extend([p.strip() for p in part.split(sep) if p.strip()])
        parts = next_parts or parts
    return [p for p in parts if p]


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
    chunks = _split_query_chunks(query_norm)
    query_tokens = [t for t in query_norm.split() if t]
    short_generic_only = len(query_tokens) <= 2 and all(t in _GENERIC_ONLY_TERMS for t in query_tokens)

    best = 0.0
    details = ""
    for term in terms:
        if not term:
            continue

        score = 0.0
        local_details: list[str] = []
        padded_q = f" {query_norm} "
        padded_t = f" {term} "
        if query_norm == term:
            score += 1.0
            local_details.append("exact")
        elif padded_t in padded_q:
            score += 0.95
            local_details.append("boundary_contains")
        elif term in query_norm:
            score += 0.82
            local_details.append("contains")

        for chunk in chunks:
            c = _safe_str(chunk)
            if not c:
                continue
            if c == term:
                score += 0.35
                local_details.append("chunk_exact")
            elif f" {term} " in f" {c} ":
                score += 0.25
                local_details.append("chunk_boundary")

        overlap = _token_overlap_ratio(query_norm, term)
        if overlap > 0:
            boost = min(0.30, overlap * 0.30)
            score += boost
            local_details.append(f"token_overlap={overlap:.2f}")

        if short_generic_only:
            score -= 0.25
            local_details.append("short_generic_penalty")

        score = max(0.0, min(1.0, score))
        if score > best:
            best = score
            details = ",".join(local_details)

    logger.debug(
        "symptoms_detector score | query=%s | symptom=%s | score=%.3f | details=%s",
        query_norm,
        symptom_norm,
        best,
        details,
    )
    return best


def _looks_like_weak_symptom_query(query_norm: str) -> bool:
    tokens = [t for t in query_norm.split() if t]
    if not tokens:
        return False
    if all(t in _GENERIC_ONLY_TERMS for t in tokens):
        return True
    return any(h in query_norm for h in _SYMPTOM_QUERY_HINTS) or any(t in _GENERIC_ONLY_TERMS for t in tokens)


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
    strong_matches = [(s, r) for s, r in scored_records if s >= 0.78]

    if not strong_matches:
        top_score = float(scored_records[0][0])
        if top_score >= 0.55 or _looks_like_weak_symptom_query(query_norm):
            logger.debug(
                "symptoms_detector clarification | query=%s | top_score=%.3f | reason=low_confidence",
                query_norm,
                top_score,
            )
            return {
                "type": "symptom_clarification",
                "symptoms": [],
                "tests": [],
                "packages": [],
                "answer": _CLARIFICATION_MESSAGE,
            }
        return None

    limited_matches = strong_matches[:4]
    symptoms: list[str] = []
    tests_seen: set[str] = set()
    packages_seen: set[str] = set()
    merged_tests: list[str] = []
    merged_packages: list[str] = []

    for _, record in limited_matches:
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

    merged_tests = merged_tests[:8]
    merged_packages = merged_packages[:3]

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
        "symptoms": symptoms,
        "tests": merged_tests,
        "packages": merged_packages,
    }
