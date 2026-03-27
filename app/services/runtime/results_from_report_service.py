"""Deterministic bridge: extracted report text -> results_engine interpretations."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from app.services.runtime.results_engine import interpret_result_query, load_results_records
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
_NOISE_HINTS = ("باقة", "package", "offer", "عرض")


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _compact_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", _safe_str(text)).strip()


def _normalize_digits(text: str) -> str:
    return _safe_str(text).translate(
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


def _is_successful_interpretation(answer: str) -> bool:
    text = _safe_str(answer)
    if not text:
        return False
    return _MANUAL_FALLBACK not in text


def _is_noise_line(line: str) -> bool:
    norm = normalize_arabic(line)
    if not norm:
        return True
    if any(marker in norm for marker in _NARRATIVE_MARKERS):
        return True
    if len(line) > 180 and " " in line:
        return True
    return False


def _canonicalize_test_name_for_query(name: str) -> str:
    text = _compact_spaces(name)
    if not text:
        return ""
    text = re.sub(r"\([^)]*\)", " ", text)
    text = text.replace(" -Total", " ")
    return _compact_spaces(text.strip(" -"))


@lru_cache(maxsize=1)
def _build_test_term_index() -> list[tuple[str, str]]:
    """Return normalized term -> canonical test name list sorted by term length desc."""
    rows = load_results_records()
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for row in rows:
        canonical = _safe_str(row.get("test_name"))
        if not canonical:
            continue

        candidates: list[str] = [canonical]
        for alias in row.get("aliases") or []:
            alias_text = _safe_str(alias)
            if not alias_text:
                continue
            alias_norm = normalize_arabic(alias_text)
            if any(h in alias_norm for h in _NOISE_HINTS):
                continue
            if len(alias_text) > 90:
                continue
            candidates.append(alias_text)

        for candidate in candidates:
            candidate_norm = normalize_arabic(candidate)
            if len(candidate_norm) < 2:
                continue
            key = (candidate_norm, canonical)
            if key in seen:
                continue
            seen.add(key)
            pairs.append(key)

    pairs.sort(key=lambda x: len(x[0]), reverse=True)
    return pairs


def _find_closest_test_name(line: str) -> tuple[str, tuple[int, int]] | None:
    line_norm = normalize_arabic(line)
    if not line_norm:
        return None

    best_name = ""
    best_span = (-1, -1)
    best_len = -1

    for term_norm, canonical in _build_test_term_index():
        idx = line_norm.find(term_norm)
        if idx < 0:
            continue
        if len(term_norm) > best_len:
            best_len = len(term_norm)
            best_name = canonical
            best_span = (idx, idx + len(term_norm))

    if not best_name:
        return None
    return best_name, best_span


def _extract_numeric_candidates(line: str) -> list[tuple[float, tuple[int, int]]]:
    normalized = _normalize_digits(line)
    if re.search(r"\b\d+\s*:\s*\d+\b", normalized):
        return []

    out: list[tuple[float, tuple[int, int]]] = []
    for m in re.finditer(r"(?<![A-Za-z\u0621-\u063A\u0641-\u064A])[-+]?\d+(?:\.\d+)?(?![A-Za-z\u0621-\u063A\u0641-\u064A])", normalized):
        raw = _safe_str(m.group(0))
        if not raw:
            continue
        try:
            out.append((float(raw), (m.start(), m.end())))
        except ValueError:
            continue
    return out


def _pick_closest_value(line: str, name_span: tuple[int, int]) -> float | None:
    numbers = _extract_numeric_candidates(line)
    if not numbers:
        return None

    best_value: float | None = None
    best_score: float | None = None
    left, right = name_span
    norm_line = _normalize_digits(line)

    for value, (n_start, n_end) in numbers:
        distance = min(abs(n_end - left), abs(n_start - right))

        # Penalize numbers that appear to be part of a reference range.
        around = norm_line[max(0, n_start - 2) : min(len(norm_line), n_end + 2)]
        penalty = 1000 if "-" in around else 0
        score = float(distance + penalty)

        if best_score is None or score < best_score:
            best_score = score
            best_value = value

    return best_value


def _extract_rows_line_by_line(report_text: str) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    rows: list[dict[str, Any]] = []
    selected_lines: list[str] = []
    ignored_lines: list[str] = []

    for raw_line in (report_text or "").splitlines():
        line = _compact_spaces(raw_line)
        if not line:
            continue

        if _is_noise_line(line):
            ignored_lines.append(line)
            continue

        if not re.search(r"\d", _normalize_digits(line)):
            ignored_lines.append(line)
            continue

        name_hit = _find_closest_test_name(line)
        if not name_hit:
            ignored_lines.append(line)
            continue

        test_name, name_span = name_hit
        value = _pick_closest_value(line, name_span)
        if value is None:
            ignored_lines.append(line)
            continue

        rows.append(
            {
                "line": line,
                "test_name": test_name,
                "result_value": value,
            }
        )
        selected_lines.append(line)

    return rows, selected_lines, ignored_lines


def interpret_uploaded_lab_report_text(report_text: str) -> dict[str, Any]:
    parsed_rows, selected_lines, ignored_lines = _extract_rows_line_by_line(report_text or "")

    items: list[dict[str, Any]] = []
    seen_tests: set[str] = set()
    built_queries: list[str] = []

    for row in parsed_rows:
        raw_name = _safe_str(row.get("test_name"))
        query_name = _canonicalize_test_name_for_query(raw_name)
        if not query_name:
            continue

        value = row.get("result_value")
        if not isinstance(value, (float, int)):
            continue

        test_key = normalize_arabic(query_name)
        if test_key in seen_tests:
            continue

        query = f"{query_name} {float(value)}"
        built_queries.append(query)
        interpretation = _safe_str(interpret_result_query(query))
        if not _is_successful_interpretation(interpretation):
            continue

        seen_tests.add(test_key)
        items.append(
            {
                "test_name": raw_name,
                "value": float(value),
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
                "selected_result_lines": selected_lines[:80],
                "ignored_noise_lines": ignored_lines[:300],
                "built_queries": built_queries[:80],
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
            "selected_result_lines": selected_lines[:80],
            "ignored_noise_lines": ignored_lines[:300],
            "built_queries": built_queries[:80],
        },
    }
