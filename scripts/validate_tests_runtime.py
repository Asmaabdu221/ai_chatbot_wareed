from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

RUNTIME_PATH = Path("app/data/runtime/rag/tests_clean.jsonl")

REQUIRED_FIELDS = {
    "source",
    "id",
    "page_type",
    "source_type",
    "domain",
    "test_name_ar",
    "title",
    "h1",
    "code_tokens",
    "tags",
    "summary_ar",
    "content_clean",
    "url",
    "summary_length",
    "content_length",
    "chunk_exists",
    "chunk_count",
    "review_issues",
    "is_active",
}


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _is_bool(value: Any) -> bool:
    return isinstance(value, bool)


def _to_float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = _safe_str(value)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def validate_tests_runtime(path: Path = RUNTIME_PATH) -> tuple[bool, list[str], dict[str, Any]]:
    errors: list[str] = []
    rows: list[dict[str, Any]] = []
    by_page_type: Counter[str] = Counter()
    by_source_type: Counter[str] = Counter()
    by_domain: Counter[str] = Counter()
    rows_with_review_issues = 0
    rows_empty_summary_ar = 0
    rows_empty_content_clean = 0

    if not path.exists():
        return False, [f"runtime file not found: {path.as_posix()}"], {}

    for line_no, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"line {line_no}: invalid JSON ({exc})")
            continue
        if not isinstance(obj, dict):
            errors.append(f"line {line_no}: row is not an object")
            continue
        rows.append(obj)

    if not rows:
        errors.append("runtime dataset has no records")
        return False, errors, {}

    seen_ids: set[str] = set()
    duplicate_ids: set[str] = set()

    for idx, row in enumerate(rows, start=1):
        missing = REQUIRED_FIELDS - set(row.keys())
        if missing:
            errors.append(f"row {idx}: missing required fields: {sorted(missing)}")
            continue

        row_id = _safe_str(row.get("id"))
        if not row_id:
            errors.append(f"row {idx}: empty id")
        elif row_id in seen_ids:
            duplicate_ids.add(row_id)
        else:
            seen_ids.add(row_id)

        test_name_ar = _safe_str(row.get("test_name_ar"))
        if not test_name_ar:
            errors.append(f"row {idx}: empty test_name_ar")

        page_type = _safe_str(row.get("page_type"))
        if not page_type:
            errors.append(f"row {idx}: empty page_type")
        else:
            by_page_type[page_type] += 1

        source_type = _safe_str(row.get("source_type"))
        if not source_type:
            errors.append(f"row {idx}: empty source_type")
        else:
            by_source_type[source_type] += 1

        domain = _safe_str(row.get("domain"))
        by_domain[domain] += 1

        summary_length = _to_float_or_none(row.get("summary_length"))
        if summary_length is None:
            errors.append(f"row {idx}: summary_length must be a number")
        elif summary_length < 0:
            errors.append(f"row {idx}: summary_length must not be negative")

        content_length = _to_float_or_none(row.get("content_length"))
        if content_length is None:
            errors.append(f"row {idx}: content_length must be a number")
        elif content_length < 0:
            errors.append(f"row {idx}: content_length must not be negative")

        chunk_count = _to_float_or_none(row.get("chunk_count"))
        if chunk_count is None:
            errors.append(f"row {idx}: chunk_count must be a number")
        elif chunk_count < 0:
            errors.append(f"row {idx}: chunk_count must not be negative")

        if not _is_bool(row.get("chunk_exists")):
            errors.append(f"row {idx}: chunk_exists must be boolean")

        if not _is_bool(row.get("is_active")):
            errors.append(f"row {idx}: is_active must be boolean")

        if _safe_str(row.get("review_issues")):
            rows_with_review_issues += 1
        if not _safe_str(row.get("summary_ar")):
            rows_empty_summary_ar += 1
        if not _safe_str(row.get("content_clean")):
            rows_empty_content_clean += 1

    if duplicate_ids:
        errors.append(f"duplicate ids found: {len(duplicate_ids)}")

    summary = {
        "total_rows": len(rows),
        "counts_by_page_type": dict(sorted(by_page_type.items(), key=lambda x: x[0])),
        "counts_by_source_type": dict(sorted(by_source_type.items(), key=lambda x: x[0])),
        "counts_by_domain": dict(sorted(by_domain.items(), key=lambda x: x[0])),
        "rows_with_review_issues": rows_with_review_issues,
        "rows_with_empty_summary_ar": rows_empty_summary_ar,
        "rows_with_empty_content_clean": rows_empty_content_clean,
    }
    return not errors, errors, summary


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ok, errors, summary = validate_tests_runtime()
    print(f"RUNTIME: {RUNTIME_PATH.as_posix()}")
    print(f"TOTAL_ROWS: {summary.get('total_rows', 0)}")

    print("COUNTS_BY_PAGE_TYPE:")
    for k, v in (summary.get("counts_by_page_type") or {}).items():
        print(f"- {k}: {v}")

    print("COUNTS_BY_SOURCE_TYPE:")
    for k, v in (summary.get("counts_by_source_type") or {}).items():
        print(f"- {k}: {v}")

    print("COUNTS_BY_DOMAIN:")
    for k, v in (summary.get("counts_by_domain") or {}).items():
        print(f"- {k}: {v}")

    print(f"ROWS_WITH_REVIEW_ISSUES: {summary.get('rows_with_review_issues', 0)}")
    print(f"ROWS_WITH_EMPTY_SUMMARY_AR: {summary.get('rows_with_empty_summary_ar', 0)}")
    print(f"ROWS_WITH_EMPTY_CONTENT_CLEAN: {summary.get('rows_with_empty_content_clean', 0)}")

    if ok:
        print("VALIDATION: PASS")
        return 0

    print("VALIDATION: FAIL")
    for err in errors:
        print(f"- {err}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
