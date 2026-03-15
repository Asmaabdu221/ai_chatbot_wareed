"""Load canonical FAQ records from runtime faq_clean.jsonl."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.services.runtime.text_normalizer import normalize_arabic

FAQ_JSONL_PATH = Path("app/data/runtime/rag/faq_clean.jsonl")


def _safe_str(value: Any) -> str:
    """Convert any value to a stripped string safely."""
    return str(value or "").strip()


def _is_valid_faq_record(parsed: Any) -> bool:
    """Return True when a parsed JSONL row looks like a usable FAQ record."""
    if not isinstance(parsed, dict):
        return False

    question = _safe_str(parsed.get("question"))
    answer = _safe_str(parsed.get("answer"))

    if not question or not answer:
        return False

    return True


def _normalize_faq_record(parsed: dict[str, Any]) -> dict[str, Any]:
    """Normalize one FAQ record while preserving extra fields."""
    item = dict(parsed)

    question = _safe_str(item.get("question"))
    answer = _safe_str(item.get("answer"))
    record_id = _safe_str(item.get("id"))
    source = _safe_str(item.get("source"))

    q_norm = _safe_str(item.get("q_norm"))
    if not q_norm:
        q_norm = normalize_arabic(question)
    else:
        q_norm = normalize_arabic(q_norm)

    item["id"] = record_id
    item["source"] = source
    item["question"] = question
    item["answer"] = answer
    item["q_norm"] = q_norm

    return item


@lru_cache(maxsize=1)
def load_faq_records() -> list[dict[str, Any]]:
    """Load, validate, normalize, and cache FAQ records from JSONL."""
    records: list[dict[str, Any]] = []

    if not FAQ_JSONL_PATH.exists():
        return records

    with FAQ_JSONL_PATH.open("r", encoding="utf-8") as f:
        for raw_line in f:
            line = _safe_str(raw_line)
            if not line:
                continue

            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue

            if not _is_valid_faq_record(parsed):
                continue

            records.append(_normalize_faq_record(parsed))

    return records


def get_faq_record_by_id(record_id: str) -> dict[str, Any] | None:
    """Return a FAQ record by exact id match, or None if not found."""
    target = _safe_str(record_id)
    if not target:
        return None

    for record in load_faq_records():
        if _safe_str(record.get("id")) == target:
            return record

    return None


def get_faq_record_count() -> int:
    """Return the total number of loaded FAQ records."""
    return len(load_faq_records())


if __name__ == "__main__":
    records = load_faq_records()
    print(f"Total FAQ records: {len(records)}")

    for record in records[:3]:
        print("-" * 48)
        print(f"ID      : {record.get('id', '')}")
        print(f"QUESTION: {record.get('question', '')}")
        print(f"Q_NORM  : {record.get('q_norm', '')}")
