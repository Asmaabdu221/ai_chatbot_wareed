"""Shared deterministic description index for tests definition/benefit fields."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.services.runtime.text_normalizer import normalize_arabic

TESTS_DESCRIPTION_JSONL_PATH = Path("app/data/runtime/rag/tests_clean.jsonl")


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _norm(value: Any) -> str:
    return normalize_arabic(_safe_str(value))


def _as_list_of_str(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_safe_str(v) for v in value if _safe_str(v)]
    text = _safe_str(value)
    if not text:
        return []
    return [part.strip() for part in text.split(",") if part.strip()]


def _tokenize(text_norm: str) -> list[str]:
    return [tok for tok in _safe_str(text_norm).split() if tok]


def _primary_text(record: dict[str, Any]) -> str:
    return _safe_str(record.get("test_name_ar")) or _safe_str(record.get("title")) or _safe_str(record.get("h1"))


def _score_description_match(query_norm: str, record: dict[str, Any]) -> tuple[float, str]:
    if not query_norm:
        return 0.0, "empty_query"

    fields = (
        ("test_name", _safe_str(record.get("test_name_norm"))),
        ("title", _safe_str(record.get("title_norm"))),
        ("h1", _safe_str(record.get("h1_norm"))),
    )
    for method, value in fields:
        if value and query_norm == value:
            return 1.0, f"exact_{method}"

    padded = f" {query_norm} "
    for method, value in fields:
        if not value:
            continue
        if f" {value} " in padded:
            return 0.96, f"boundary_{method}"
        if value in query_norm:
            return 0.92, f"contains_{method}"
        if query_norm in value and len(query_norm) >= 4:
            return 0.86, f"contained_by_{method}"

    code_tokens = list(record.get("code_tokens_norm") or [])
    for token in code_tokens:
        if not token:
            continue
        if f" {token} " in padded or token in query_norm:
            return 0.95, "code_token"

    query_tokens = set(_tokenize(query_norm))
    if not query_tokens:
        return 0.0, "no_tokens"
    fallback_tokens = {"تحليل", "فحص", "اختبار", "ايش", "ما", "هو", "هذا", "فائدة", "يفيد", "ليش", "نسوي"}
    query_tokens = {t for t in query_tokens if t not in fallback_tokens and len(t) > 1}
    if not query_tokens:
        return 0.0, "generic_tokens_only"

    candidate_tokens = set(_tokenize(" ".join(
        [
            _safe_str(record.get("test_name_norm")),
            _safe_str(record.get("title_norm")),
            _safe_str(record.get("h1_norm")),
            " ".join(record.get("code_tokens_norm") or []),
        ]
    )))
    overlap = query_tokens.intersection(candidate_tokens)
    if not overlap:
        return 0.0, "no_overlap"
    ratio = len(overlap) / max(1, len(query_tokens))
    if ratio >= 0.75:
        return 0.84, "token_overlap_strong"
    if ratio >= 0.5:
        return 0.72, "token_overlap_moderate"
    return 0.0, "token_overlap_weak"


@lru_cache(maxsize=1)
def load_test_description_records() -> list[dict[str, Any]]:
    """Load normalized test description records from tests_clean JSONL."""
    if not TESTS_DESCRIPTION_JSONL_PATH.exists():
        return []

    rows: list[dict[str, Any]] = []
    with TESTS_DESCRIPTION_JSONL_PATH.open("r", encoding="utf-8") as f:
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

            test_name_ar = _safe_str(obj.get("test_name_ar"))
            title = _safe_str(obj.get("title"))
            h1 = _safe_str(obj.get("h1"))
            if not (test_name_ar or title or h1):
                continue

            item = {
                "id": _safe_str(obj.get("id")),
                "test_name_ar": test_name_ar,
                "title": title,
                "h1": h1,
                "summary_ar": _safe_str(obj.get("summary_ar")),
                "benefit_ar": _safe_str(obj.get("benefit_ar")),
                "content_clean": _safe_str(obj.get("content_clean")),
                "code_tokens": _as_list_of_str(obj.get("code_tokens")),
            }
            item["test_name_norm"] = _norm(item["test_name_ar"])
            item["title_norm"] = _norm(item["title"])
            item["h1_norm"] = _norm(item["h1"])
            item["code_tokens_norm"] = [_norm(t) for t in item["code_tokens"] if _norm(t)]
            rows.append(item)
    return rows


@lru_cache(maxsize=1)
def build_test_description_index() -> dict[str, dict[str, Any]]:
    """Build exact normalized lookup index from primary identity fields."""
    index: dict[str, dict[str, Any]] = {}
    for record in load_test_description_records():
        keys = [
            _safe_str(record.get("test_name_norm")),
            _safe_str(record.get("title_norm")),
            _safe_str(record.get("h1_norm")),
        ]
        keys.extend(list(record.get("code_tokens_norm") or []))
        for key in keys:
            if key and key not in index:
                index[key] = record
    return index


def find_test_description_record(query_or_name: str) -> dict[str, Any] | None:
    """
    Find the best deterministic description record for a query/name string.

    Returns a shallow copy with optional `_match_score` and `_match_method`.
    """
    query_norm = _norm(query_or_name)
    if not query_norm:
        return None

    index = build_test_description_index()
    exact = index.get(query_norm)
    if exact is not None:
        out = dict(exact)
        out["_match_score"] = 1.0
        out["_match_method"] = "exact_index"
        return out

    def _is_effectively_same_description_entity(
        first: dict[str, Any] | None,
        second: dict[str, Any] | None,
    ) -> bool:
        if not first or not second:
            return False
        identity_equal = (
            _norm(first.get("test_name_ar")) == _norm(second.get("test_name_ar"))
            and _norm(first.get("title")) == _norm(second.get("title"))
            and _norm(first.get("h1")) == _norm(second.get("h1"))
        )
        content_equal = (
            _safe_str(first.get("summary_ar")) == _safe_str(second.get("summary_ar"))
            and _safe_str(first.get("benefit_ar")) == _safe_str(second.get("benefit_ar"))
        )
        return identity_equal and content_equal

    best: dict[str, Any] | None = None
    best_score = 0.0
    best_method = ""
    second_score = 0.0
    second: dict[str, Any] | None = None
    for record in load_test_description_records():
        score, method = _score_description_match(query_norm, record)
        if score > best_score:
            second_score = best_score
            second = best
            best = record
            best_score = score
            best_method = method
        elif score > second_score:
            second_score = score
            second = record

    if best is None or best_score < 0.72:
        return None
    if second_score >= 0.72 and (best_score - second_score) <= 0.04:
        same_top_duplicate = (
            abs(best_score - second_score) <= 1e-9
            and _is_effectively_same_description_entity(best, second)
        )
        if not same_top_duplicate:
            return None

    out = dict(best)
    out["_match_score"] = best_score
    out["_match_method"] = best_method or "scored_match"
    return out


def find_test_description_for_business_target(test_name: str) -> dict[str, Any] | None:
    """Light helper for business engine reuse without duplicating fields."""
    return find_test_description_record(test_name)
