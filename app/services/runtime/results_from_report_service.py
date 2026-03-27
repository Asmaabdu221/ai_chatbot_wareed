"""Deterministic bridge: parsed report text -> results_engine interpretations."""

from __future__ import annotations

import re
from typing import Any

from app.services.report_parser_service import parse_lab_report_text
from app.services.runtime.results_engine import interpret_result_query
from app.services.runtime.text_normalizer import normalize_arabic

_MANUAL_FALLBACK = "أرسل صورة التحليل أو اكتب اسم التحليل مع النتيجة والمرجع الأدنى والأعلى."


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _extract_simple_numeric(value_text: str) -> float | None:
    text = _safe_str(value_text)
    if not text:
        return None
    # Skip ratio-like strings (e.g. 1:80) in this first safe version.
    if ":" in text:
        return None
    normalized = text.translate(
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
                ",": ".",
                "٫": ".",
            }
        )
    )
    compact = re.sub(r"\s+", "", normalized)
    # Keep this strict to avoid guessing unclear values (ranges/operators/mixed tokens).
    if not re.fullmatch(r"[-+]?\d+(?:\.\d+)?", compact):
        return None
    try:
        return float(compact)
    except ValueError:
        return None


def _is_clear_test_name(raw_name: str) -> bool:
    name = _safe_str(raw_name)
    if not name:
        return False
    name_norm = normalize_arabic(name)
    if len(name_norm) < 2:
        return False
    return bool(re.search(r"[A-Za-z\u0621-\u063A\u0641-\u064A]", name))


def _is_successful_interpretation(answer: str) -> bool:
    text = _safe_str(answer)
    if not text:
        return False
    return _MANUAL_FALLBACK not in text


def interpret_uploaded_lab_report_text(report_text: str) -> dict[str, Any]:
    parsed_rows = parse_lab_report_text(report_text or "")
    items: list[dict[str, Any]] = []
    seen_tests: set[str] = set()

    for row in parsed_rows:
        raw_name = _safe_str(row.get("test_name"))
        if not _is_clear_test_name(raw_name):
            continue

        value = _extract_simple_numeric(_safe_str(row.get("result_value")))
        if value is None:
            continue

        test_key = normalize_arabic(raw_name)
        if test_key in seen_tests:
            continue

        query = f"{raw_name} {value}"
        interpretation = _safe_str(interpret_result_query(query))
        if not _is_successful_interpretation(interpretation):
            continue

        seen_tests.add(test_key)
        items.append(
            {
                "test_name": raw_name,
                "value": value,
                "query": query,
                "interpretation": interpretation,
            }
        )

    if not items:
        return {
            "matched": False,
            "items": [],
            "answer": _MANUAL_FALLBACK,
        }

    lines = ["قرأت القيم الواضحة من التقرير، والتفسير المبدئي كالتالي:"]
    for i, item in enumerate(items[:6], start=1):
        lines.append(f"{i}) {item['test_name']} = {item['value']}")
        lines.append(item["interpretation"])
    return {
        "matched": True,
        "items": items,
        "answer": "\n".join(lines),
    }
