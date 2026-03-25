from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

RUNTIME_PATH = Path("app/data/runtime/rag/tests_business_clean.jsonl")

REQUIRED_FIELDS = {
    "source",
    "id",
    "test_name_ar",
    "category",
    "benefit",
    "price_raw",
    "price_number",
    "sample_type",
    "symptoms",
    "preparation",
    "complementary_tests",
    "alternative_tests",
    "review_issues",
    "source_row",
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


def validate_tests_business_runtime(path: Path = RUNTIME_PATH) -> tuple[bool, list[str], dict[str, Any]]:
    errors: list[str] = []
    rows: list[dict[str, Any]] = []
    counts_by_category: Counter[str] = Counter()
    rows_missing_price_number = 0
    rows_with_review_issues = 0
    rows_with_empty_preparation = 0
    rows_with_empty_symptoms = 0

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

        category = _safe_str(row.get("category"))
        if not category:
            errors.append(f"row {idx}: empty category")
        else:
            counts_by_category[category] += 1

        price_number = _to_float_or_none(row.get("price_number"))
        if price_number is None:
            rows_missing_price_number += 1
        elif price_number < 0:
            errors.append(f"row {idx}: price_number must not be negative")

        if not _is_bool(row.get("is_active")):
            errors.append(f"row {idx}: is_active must be boolean")

        if _safe_str(row.get("review_issues")):
            rows_with_review_issues += 1
        if not _safe_str(row.get("preparation")):
            rows_with_empty_preparation += 1

        symptoms = row.get("symptoms")
        if isinstance(symptoms, list):
            if not any(_safe_str(item) for item in symptoms):
                rows_with_empty_symptoms += 1
        elif not _safe_str(symptoms):
            rows_with_empty_symptoms += 1

    if duplicate_ids:
        errors.append(f"duplicate ids found: {len(duplicate_ids)}")

    summary = {
        "total_rows": len(rows),
        "counts_by_category": dict(sorted(counts_by_category.items(), key=lambda x: x[0])),
        "rows_missing_price_number": rows_missing_price_number,
        "rows_with_review_issues": rows_with_review_issues,
        "rows_with_empty_preparation": rows_with_empty_preparation,
        "rows_with_empty_symptoms": rows_with_empty_symptoms,
    }
    return not errors, errors, summary


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ok, errors, summary = validate_tests_business_runtime()
    print(f"RUNTIME: {RUNTIME_PATH.as_posix()}")
    print(f"TOTAL_ROWS: {summary.get('total_rows', 0)}")
    print("COUNTS_BY_CATEGORY:")
    for k, v in (summary.get("counts_by_category") or {}).items():
        print(f"- {k}: {v}")
    print(f"ROWS_MISSING_PRICE_NUMBER: {summary.get('rows_missing_price_number', 0)}")
    print(f"ROWS_WITH_REVIEW_ISSUES: {summary.get('rows_with_review_issues', 0)}")
    print(f"ROWS_WITH_EMPTY_PREPARATION: {summary.get('rows_with_empty_preparation', 0)}")
    print(f"ROWS_WITH_EMPTY_SYMPTOMS: {summary.get('rows_with_empty_symptoms', 0)}")

    if ok:
        print("VALIDATION: PASS")
        return 0

    print("VALIDATION: FAIL")
    for err in errors:
        print(f"- {err}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
