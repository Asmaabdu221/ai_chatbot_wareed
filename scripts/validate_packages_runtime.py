from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

RUNTIME_PATH = Path("app/data/runtime/rag/packages_clean.jsonl")

REQUIRED_FIELDS = {
    "source",
    "id",
    "main_category",
    "offering_type",
    "package_name",
    "description_short",
    "description_full",
    "price_raw",
    "price_number",
    "currency",
    "included_count",
    "runtime_present",
    "review_issues",
    "source_row",
    "is_active",
}

ALLOWED_OFFERING_TYPES = {
    "package",
    "single_test",
    "genetic_test",
    "genetic_package",
    "self_collection_test",
    "self_collection_package",
}


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _is_bool(value: Any) -> bool:
    return isinstance(value, bool)


def _is_number_or_none(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (int, float)):
        return True
    text = _safe_str(value)
    if not text:
        return True
    try:
        float(text)
        return True
    except ValueError:
        return False


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


def validate_packages_runtime(path: Path = RUNTIME_PATH) -> tuple[bool, list[str], dict[str, Any]]:
    errors: list[str] = []
    rows: list[dict[str, Any]] = []
    category_counts: Counter[str] = Counter()
    type_counts: Counter[str] = Counter()
    missing_price_number = 0
    rows_with_review_issues = 0

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

        package_name = _safe_str(row.get("package_name"))
        if not package_name:
            errors.append(f"row {idx}: empty package_name")

        main_category = _safe_str(row.get("main_category"))
        if not main_category:
            errors.append(f"row {idx}: empty main_category")
        else:
            category_counts[main_category] += 1

        offering_type = _safe_str(row.get("offering_type")).lower()
        if not offering_type:
            errors.append(f"row {idx}: empty offering_type")
        else:
            if offering_type not in ALLOWED_OFFERING_TYPES:
                errors.append(
                    f"row {idx}: invalid offering_type '{offering_type}' "
                    f"(allowed: {sorted(ALLOWED_OFFERING_TYPES)})"
                )
            type_counts[offering_type] += 1

        if not _is_number_or_none(row.get("price_number")):
            errors.append(f"row {idx}: price_number must be number or null")
        else:
            pn = _to_float_or_none(row.get("price_number"))
            if pn is None:
                missing_price_number += 1
            elif pn < 0:
                errors.append(f"row {idx}: price_number must not be negative")

        if not _is_bool(row.get("runtime_present")):
            errors.append(f"row {idx}: runtime_present must be boolean")

        if not _is_bool(row.get("is_active")):
            errors.append(f"row {idx}: is_active must be boolean")

        if _safe_str(row.get("review_issues")):
            rows_with_review_issues += 1

    if duplicate_ids:
        errors.append(f"duplicate ids found: {len(duplicate_ids)}")

    summary = {
        "rows": len(rows),
        "counts_by_main_category": dict(sorted(category_counts.items(), key=lambda x: x[0])),
        "counts_by_offering_type": dict(sorted(type_counts.items(), key=lambda x: x[0])),
        "rows_missing_price_number": missing_price_number,
        "rows_with_review_issues": rows_with_review_issues,
    }
    return not errors, errors, summary


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ok, errors, summary = validate_packages_runtime()
    print(f"RUNTIME: {RUNTIME_PATH.as_posix()}")
    print(f"ROWS: {summary.get('rows', 0)}")
    print("COUNTS_BY_MAIN_CATEGORY:")
    for k, v in (summary.get("counts_by_main_category") or {}).items():
        print(f"- {k}: {v}")
    print("COUNTS_BY_OFFERING_TYPE:")
    for k, v in (summary.get("counts_by_offering_type") or {}).items():
        print(f"- {k}: {v}")
    print(f"ROWS_MISSING_PRICE_NUMBER: {summary.get('rows_missing_price_number', 0)}")
    print(f"ROWS_WITH_REVIEW_ISSUES: {summary.get('rows_with_review_issues', 0)}")

    if ok:
        print("VALIDATION: PASS")
        return 0

    print("VALIDATION: FAIL")
    for err in errors:
        print(f"- {err}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
