"""Deterministic symptom-to-tests/package suggestion engine."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.services.runtime.text_normalizer import normalize_arabic

SYMPTOMS_MAPPING_JSONL_PATH = Path("app/data/runtime/rag/symptoms_mapping.jsonl")


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _norm(value: Any) -> str:
    return normalize_arabic(_safe_str(value))


def _as_list_of_str(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_safe_str(v) for v in value if _safe_str(v)]
    text = _safe_str(value)
    return [text] if text else []


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
    best = 0.0
    for term in terms:
        if not term:
            continue
        if query_norm == term:
            return 1.0
        if term in query_norm:
            best = max(best, 0.95)
        elif len(query_norm) >= 4 and query_norm in term:
            best = max(best, 0.75)
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
