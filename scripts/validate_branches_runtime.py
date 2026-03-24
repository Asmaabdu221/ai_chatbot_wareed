from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.runtime.branches_resolver import _CITY_CANONICAL_ALIASES
from app.services.runtime.text_normalizer import normalize_arabic

RUNTIME_PATH = Path("app/data/runtime/rag/branches_with_coordinates.jsonl")

REQUIRED_FIELDS = {
    "source",
    "id",
    "city",
    "district",
    "branch_name",
    "hours",
    "map_url",
    "maps_url",
    "latitude",
    "longitude",
    "contact_phone",
    "is_active",
}


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _is_float_or_none(value: Any) -> bool:
    if value is None:
        return True
    text = _safe_str(value)
    if not text:
        return True
    try:
        float(text)
        return True
    except (TypeError, ValueError):
        return False


def validate_runtime_file(path: Path = RUNTIME_PATH) -> tuple[bool, list[str], dict[str, int]]:
    errors: list[str] = []
    city_counts: Counter[str] = Counter()
    rows: list[dict[str, Any]] = []

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
            errors.append(f"line {line_no}: record is not an object")
            continue
        rows.append(obj)

    if not rows:
        errors.append("runtime dataset has no records")
        return False, errors, {}

    ids_seen: set[str] = set()
    duplicates: set[str] = set()

    alias_norm_to_canonical_norm: dict[str, str] = {}
    canonical_city_norms: set[str] = set()
    for alias, canonical in _CITY_CANONICAL_ALIASES.items():
        alias_norm = normalize_arabic(alias)
        canonical_norm = normalize_arabic(canonical)
        alias_norm_to_canonical_norm[alias_norm] = canonical_norm
        canonical_city_norms.add(canonical_norm)

    dataset_city_norms: set[str] = set()

    for idx, row in enumerate(rows, start=1):
        missing = REQUIRED_FIELDS - set(row.keys())
        if missing:
            errors.append(f"row {idx}: missing required fields: {sorted(missing)}")
            continue

        row_id = _safe_str(row.get("id"))
        if not row_id:
            errors.append(f"row {idx}: empty id")
        elif row_id in ids_seen:
            duplicates.add(row_id)
        else:
            ids_seen.add(row_id)

        city = _safe_str(row.get("city"))
        if not city:
            errors.append(f"row {idx}: empty city")
        else:
            city_counts[city] += 1
            city_norm = normalize_arabic(city)
            dataset_city_norms.add(city_norm)
            canonical_norm = alias_norm_to_canonical_norm.get(city_norm)
            # If city is known alias form, it must already be in canonical value.
            if canonical_norm and city_norm != canonical_norm:
                errors.append(
                    f"row {idx}: non-canonical city '{city}' "
                    f"(expected canonical alias target)"
                )

        map_url = _safe_str(row.get("map_url"))
        maps_url = _safe_str(row.get("maps_url"))
        if map_url and not maps_url:
            errors.append(f"row {idx}: maps_url missing while map_url exists")
        if maps_url and not map_url:
            errors.append(f"row {idx}: map_url missing while maps_url exists")

        if not _is_float_or_none(row.get("latitude")):
            errors.append(f"row {idx}: latitude must be float or null")
        if not _is_float_or_none(row.get("longitude")):
            errors.append(f"row {idx}: longitude must be float or null")

    if duplicates:
        errors.append(f"duplicate ids found: {len(duplicates)}")

    # Alias coverage: every alias canonical target must exist in dataset cities.
    missing_canonical_targets = sorted(
        canonical_norm
        for canonical_norm in canonical_city_norms
        if canonical_norm and canonical_norm not in dataset_city_norms
    )
    if missing_canonical_targets:
        errors.append(
            "alias coverage missing canonical cities: "
            + ", ".join(missing_canonical_targets)
        )

    return not errors, errors, dict(city_counts)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ok, errors, city_counts = validate_runtime_file()
    print(f"RUNTIME: {RUNTIME_PATH.as_posix()}")
    print(f"ROWS: {sum(city_counts.values())}")
    print("CITY_COUNTS:")
    for city, count in sorted(city_counts.items(), key=lambda x: (x[0], x[1])):
        print(f"- {city}: {count}")

    if ok:
        print("VALIDATION: PASS")
        return 0

    print("VALIDATION: FAIL")
    for err in errors:
        print(f"- {err}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
