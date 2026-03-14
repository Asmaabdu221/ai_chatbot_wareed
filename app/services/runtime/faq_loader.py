"""Load canonical FAQ records from runtime faq_clean.jsonl."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.services.runtime.text_normalizer import normalize_arabic


FAQ_JSONL_PATH = Path("app/data/runtime/rag/faq_clean.jsonl")


@lru_cache(maxsize=1)
def load_faq_records() -> list[dict[str, Any]]:
    """Load, validate, and normalize FAQ records from JSONL."""
    records: list[dict[str, Any]] = []
    if not FAQ_JSONL_PATH.exists():
        return records

    with FAQ_JSONL_PATH.open("r", encoding="utf-8") as f:
        for raw_line in f:
            line = (raw_line or "").strip()
            if not line:
                continue

            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue

            if not isinstance(parsed, dict):
                continue

            question = str(parsed.get("question") or "").strip()
            answer = str(parsed.get("answer") or "").strip()
            if not question or not answer:
                continue

            item = dict(parsed)  # Preserve extra fields.
            item["id"] = str(item.get("id") or "").strip()
            item["question"] = question
            item["answer"] = answer

            q_norm = str(item.get("q_norm") or "").strip()
            item["q_norm"] = q_norm if q_norm else normalize_arabic(question)
            records.append(item)

    return records


def get_faq_record_by_id(record_id: str) -> dict[str, Any] | None:
    """Return a FAQ record with exact id match, or None if absent."""
    target = str(record_id or "").strip()
    if not target:
        return None

    for rec in load_faq_records():
        if str(rec.get("id") or "").strip() == target:
            return rec
    return None

