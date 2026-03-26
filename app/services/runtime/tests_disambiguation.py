"""Deterministic loader and matcher for ambiguous test terms."""

from __future__ import annotations

import json
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.services.runtime.text_normalizer import normalize_arabic

TESTS_DISAMBIGUATION_JSONL_PATH = Path("app/data/runtime/rag/tests_disambiguation.jsonl")
_SELECTION_TTL_SECONDS = 15 * 60
_LAST_TEST_DISAMBIGUATION: dict[str, Any] = {
    "options": [],
    "query_type": "",
    "updated_at": 0.0,
}


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _norm(value: Any) -> str:
    return normalize_arabic(_safe_str(value))


def _as_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_safe_str(v) for v in value if _safe_str(v)]
    text = _safe_str(value)
    return [text] if text else []


@lru_cache(maxsize=1)
def load_tests_disambiguation_records() -> list[dict[str, Any]]:
    """Load disambiguation rules from JSONL with normalized fields."""
    if not TESTS_DISAMBIGUATION_JSONL_PATH.exists():
        return []

    rows: list[dict[str, Any]] = []
    with TESTS_DISAMBIGUATION_JSONL_PATH.open("r", encoding="utf-8") as f:
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

            broad_term = _safe_str(obj.get("broad_term"))
            candidate_tests = _as_str_list(obj.get("candidate_tests"))
            clarify_question = _safe_str(obj.get("clarify_question"))
            if not broad_term or not candidate_tests:
                continue

            aliases = _as_str_list(obj.get("aliases"))
            row = {
                "broad_term": broad_term,
                "aliases": aliases,
                "candidate_tests": candidate_tests,
                "clarify_question": clarify_question,
                "broad_term_norm": _norm(broad_term),
                "aliases_norm": [_norm(a) for a in aliases if _norm(a)],
            }
            rows.append(row)
    return rows


def find_disambiguation_candidates(query: str) -> dict[str, Any] | None:
    """Find matching ambiguous term record using exact + substring matching."""
    query_norm = _norm(query)
    if not query_norm:
        return None

    records = load_tests_disambiguation_records()
    if not records:
        return None

    exact_match: dict[str, Any] | None = None
    best_substring_match: dict[str, Any] | None = None
    best_len = 0

    for record in records:
        terms = [record.get("broad_term_norm", "")]
        terms.extend(record.get("aliases_norm") or [])

        for term in terms:
            t = _safe_str(term)
            if not t:
                continue

            if query_norm == t:
                exact_match = record
                break

            if t in query_norm or query_norm in t:
                t_len = len(t)
                if t_len > best_len:
                    best_len = t_len
                    best_substring_match = record
        if exact_match:
            break

    selected = exact_match or best_substring_match
    if not selected:
        return None

    return {
        "broad_term": _safe_str(selected.get("broad_term")),
        "candidate_tests": _as_str_list(selected.get("candidate_tests")),
        "clarify_question": _safe_str(selected.get("clarify_question")),
    }


def format_disambiguation_reply(payload: dict[str, Any]) -> str:
    """Build a short deterministic Arabic clarification reply."""
    candidates = _as_str_list(payload.get("candidate_tests"))[:5]
    if not candidates:
        return "ما قدرت أحدد التحليل المقصود بدقة."

    clarify = _safe_str(payload.get("clarify_question")) or "هل تقصد:"
    if clarify.endswith("؟"):
        clarify = clarify[:-1]

    lines = [f"ما قدرت أحدد التحليل المقصود بدقة. {clarify}"]
    for idx, name in enumerate(candidates, start=1):
        lines.append(f"{idx}) {name}")
    return "\n".join(lines)


def set_tests_disambiguation_state(candidate_tests: list[str], query_type: str = "") -> None:
    options = [c for c in _as_str_list(candidate_tests) if c][:5]
    _LAST_TEST_DISAMBIGUATION["options"] = options
    _LAST_TEST_DISAMBIGUATION["query_type"] = _safe_str(query_type)
    _LAST_TEST_DISAMBIGUATION["updated_at"] = time.time()


def _parse_numeric_selection(text: str) -> int | None:
    value = _safe_str(text)
    if not value:
        return None
    normalized_digits = value.translate(
        str.maketrans(
            {
                "٠": "0",
                "١": "1",
                "٢": "2",
                "٣": "3",
                "٤": "4",
                "٥": "5",
                "٦": "6",
                "٧": "7",
                "٨": "8",
                "٩": "9",
            }
        )
    )
    if not re.fullmatch(r"\d{1,2}", normalized_digits):
        return None
    try:
        return int(normalized_digits)
    except ValueError:
        return None


def resolve_tests_disambiguation_selection(user_text: str) -> dict[str, Any] | None:
    selection_number = _parse_numeric_selection(user_text)
    if selection_number is None or selection_number < 1:
        return None

    updated_at = float(_LAST_TEST_DISAMBIGUATION.get("updated_at") or 0.0)
    if not updated_at or (time.time() - updated_at) > _SELECTION_TTL_SECONDS:
        return None

    options = list(_LAST_TEST_DISAMBIGUATION.get("options") or [])
    idx = selection_number - 1
    if idx < 0 or idx >= len(options):
        return None

    selected_test = _safe_str(options[idx])
    if not selected_test:
        return None
    return {
        "selected_test": selected_test,
        "query_type": _safe_str(_LAST_TEST_DISAMBIGUATION.get("query_type")),
        "selection_number": selection_number,
    }
