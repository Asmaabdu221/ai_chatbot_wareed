"""Deterministic bridge: parsed report text -> results_engine interpretations."""

from __future__ import annotations

import re
from typing import Any

from app.services.report_parser_service import parse_lab_report_text
from app.services.runtime.results_engine import interpret_result_query
from app.services.runtime.text_normalizer import normalize_arabic

_MANUAL_FALLBACK = "أرسل صورة التحليل أو اكتب اسم التحليل مع النتيجة والمرجع الأدنى والأعلى."
_NARRATIVE_MARKERS = (
    "لماذا يجرى هذا الاختبار",
    "كيف يجرى هذا الاختبار",
    "زيارة موصى بها للطبيب",
    "اخر قراءة",
    "آخر قراءة",
    "المريض",
    "المختبر",
    "تاريخ التقرير",
)
_ROW_PREFIX_GARBAGE = "-•*:"


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


def _canonicalize_test_name_for_query(raw_name: str) -> str:
    name = _compact_spaces(raw_name)
    if not name:
        return ""
    # Keep deterministic, minimal cleanup: remove extra parenthetical details often present in Wareed headers.
    name = re.sub(r"\([^)]*\)", " ", name)
    name = name.replace(" -Total", " ")
    name = _compact_spaces(name.strip(" -"))
    return name


def _compact_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", _safe_str(text)).strip()


def _is_noise_line(line: str) -> bool:
    norm = normalize_arabic(line)
    if not norm:
        return True
    if any(marker in norm for marker in _NARRATIVE_MARKERS):
        return True
    # Long prose-like lines are usually explanatory narrative in this report format.
    if len(line) > 180 and (" " in line):
        return True
    return False


def _clean_line(line: str) -> str:
    cleaned = _safe_str(line).strip(_ROW_PREFIX_GARBAGE).strip()
    return _compact_spaces(cleaned)


def _extract_row_from_line(line: str) -> dict[str, str] | None:
    candidate = _clean_line(line)
    if not candidate or _is_noise_line(candidate):
        return None

    # Pattern A: <unit> <value> <test_name> [range]
    # Example: g/dL 10 Hemoglobin 11.5 - 15.2
    p_a = re.match(
        r"^(?P<unit>[%A-Za-zµμ/]+)\s+(?P<value>[-+]?\d+(?:\.\d+)?)\s+(?P<name>.+?)(?:\s+(?P<range>\d+(?:\.\d+)?\s*-\s*\d+(?:\.\d+)?))?$",
        candidate,
        flags=re.IGNORECASE,
    )
    if p_a:
        return {
            "test_name": _compact_spaces(p_a.group("name")),
            "result_value": _safe_str(p_a.group("value")),
            "unit": _safe_str(p_a.group("unit")),
            "reference_range": _safe_str(p_a.group("range")),
            "flags_if_present": "",
        }

    # Pattern B: <range> <unit> <value> <test_name>
    # Example: 5.33 - 0.38 uIU/mL 4 Thyroid Stimulating Hormone (TSH)
    p_b = re.match(
        r"^(?P<range>\d+(?:\.\d+)?\s*-\s*\d+(?:\.\d+)?)\s+(?P<unit>[%A-Za-zµμ/]+)\s+(?P<value>[-+]?\d+(?:\.\d+)?)\s+(?P<name>.+)$",
        candidate,
        flags=re.IGNORECASE,
    )
    if p_b:
        return {
            "test_name": _compact_spaces(p_b.group("name")),
            "result_value": _safe_str(p_b.group("value")),
            "unit": _safe_str(p_b.group("unit")),
            "reference_range": _safe_str(p_b.group("range")),
            "flags_if_present": "",
        }

    return None


def _extract_wareed_rows(report_text: str) -> tuple[list[dict[str, str]], list[str], list[str]]:
    selected_rows: list[dict[str, str]] = []
    selected_lines: list[str] = []
    ignored_lines: list[str] = []

    for raw_line in (report_text or "").splitlines():
        line = _compact_spaces(raw_line)
        if not line:
            continue
        if _is_noise_line(line):
            ignored_lines.append(line)
            continue

        parsed = _extract_row_from_line(line)
        if parsed:
            selected_rows.append(parsed)
            selected_lines.append(line)
        else:
            ignored_lines.append(line)

    return selected_rows, selected_lines, ignored_lines


def interpret_uploaded_lab_report_text(report_text: str) -> dict[str, Any]:
    parsed_rows, selected_lines, ignored_lines = _extract_wareed_rows(report_text or "")
    if not parsed_rows:
        parsed_rows = parse_lab_report_text(report_text or "")
        selected_lines = []
        ignored_lines = []
    items: list[dict[str, Any]] = []
    seen_tests: set[str] = set()
    built_queries: list[str] = []
    query_results: list[dict[str, Any]] = []

    for row in parsed_rows:
        raw_name = _safe_str(row.get("test_name"))
        if not _is_clear_test_name(raw_name):
            continue
        query_name = _canonicalize_test_name_for_query(raw_name)
        if not query_name:
            continue

        value = _extract_simple_numeric(_safe_str(row.get("result_value")))
        if value is None:
            continue

        test_key = normalize_arabic(query_name)
        if test_key in seen_tests:
            continue

        query = f"{query_name} {value}"
        built_queries.append(query)
        interpretation = _safe_str(interpret_result_query(query))
        query_results.append(
            {
                "query": query,
                "matched": _is_successful_interpretation(interpretation),
                "answer": interpretation,
            }
        )
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
            "debug": {
                "selected_result_lines": selected_lines[:50],
                "ignored_noise_lines": ignored_lines[:200],
                "built_queries": built_queries[:50],
                "query_results": query_results[:100],
            },
        }

    lines = ["قرأت القيم الواضحة من التقرير، والتفسير المبدئي كالتالي:"]
    for i, item in enumerate(items[:6], start=1):
        lines.append(f"{i}) {item['test_name']} = {item['value']}")
        lines.append(item["interpretation"])
    return {
        "matched": True,
        "items": items,
        "answer": "\n".join(lines),
        "debug": {
            "selected_result_lines": selected_lines[:50],
            "ignored_noise_lines": ignored_lines[:200],
            "built_queries": built_queries[:50],
            "query_results": query_results[:100],
        },
    }
