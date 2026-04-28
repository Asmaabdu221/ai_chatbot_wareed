from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path
from typing import Any

MARKERS = ("Ø", "Ù", "Ã", "Â", "\ufffd")
ARABIC_RE = re.compile(r"[\u0600-\u06FF]")


def marker_count(text: str) -> int:
    return sum(text.count(m) for m in MARKERS)


def has_marker(text: str) -> bool:
    return any(m in text for m in MARKERS)


def has_arabic(text: str) -> bool:
    return bool(ARABIC_RE.search(text))


def fix_mojibake(text: str) -> str:
    try:
        return text.encode("latin1").decode("utf-8")
    except Exception:
        return text


def walk_strings(value: Any, path: str = "$"):
    if isinstance(value, dict):
        for k, v in value.items():
            yield from walk_strings(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from walk_strings(v, f"{path}[{i}]")
    elif isinstance(value, str):
        yield path, value


def get_record_id(record: dict[str, Any]) -> str:
    for key in ("id", "test_id", "package_id", "branch_id", "uuid", "code"):
        value = str(record.get(key, "")).strip()
        if value:
            return value
    return ""


def repair_value(value: Any) -> tuple[Any, int]:
    changed = 0
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            nv, c = repair_value(v)
            out[k] = nv
            changed += c
        return out, changed
    if isinstance(value, list):
        out_list = []
        for item in value:
            nv, c = repair_value(item)
            out_list.append(nv)
            changed += c
        return out_list, changed
    if isinstance(value, str):
        if not has_marker(value):
            return value, 0
        repaired = fix_mojibake(value)
        if repaired == value:
            return value, 0
        if not has_arabic(repaired):
            return value, 0
        if marker_count(repaired) >= marker_count(value):
            return value, 0
        return repaired, 1
    return value, 0


def scan_jsonl(path: Path, max_examples: int = 6) -> dict[str, Any]:
    result: dict[str, Any] = {
        "file": str(path),
        "total_lines": 0,
        "parse_errors": 0,
        "corrupted_records": 0,
        "corrupted_fields": 0,
        "examples": [],
    }
    if not path.exists():
        result["missing"] = True
        return result

    with path.open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            result["total_lines"] += 1
            text = line.strip()
            if not text:
                continue
            try:
                record = json.loads(text)
            except Exception:
                result["parse_errors"] += 1
                continue
            if not isinstance(record, dict):
                continue

            record_has_corruption = False
            rec_id = get_record_id(record)
            for field_path, value in walk_strings(record):
                if not has_marker(value):
                    continue
                result["corrupted_fields"] += 1
                record_has_corruption = True
                if len(result["examples"]) < max_examples:
                    result["examples"].append(
                        {
                            "line": lineno,
                            "record_id": rec_id,
                            "field_path": field_path,
                            "value": value[:240],
                        }
                    )
            if record_has_corruption:
                result["corrupted_records"] += 1
    return result


def repair_jsonl(path: Path) -> dict[str, Any]:
    outcome = {"file": str(path), "repaired_fields": 0, "rewritten": False, "backup": ""}
    if not path.exists():
        outcome["missing"] = True
        return outcome

    new_lines: list[str] = []
    changed_total = 0

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            raw = line.rstrip("\n")
            if not raw.strip():
                new_lines.append(raw)
                continue
            try:
                record = json.loads(raw)
            except Exception:
                new_lines.append(raw)
                continue

            repaired_record, changed = repair_value(record)
            changed_total += changed
            new_lines.append(json.dumps(repaired_record, ensure_ascii=False))

    outcome["repaired_fields"] = changed_total
    if changed_total > 0:
        backup = Path(str(path) + ".bak")
        shutil.copy2(path, backup)
        with path.open("w", encoding="utf-8", newline="\n") as f:
            for line in new_lines:
                f.write(line + "\n")
        outcome["rewritten"] = True
        outcome["backup"] = str(backup)
    return outcome


def scan_excel(path: Path, max_examples: int = 6) -> dict[str, Any]:
    result: dict[str, Any] = {
        "file": str(path),
        "exists": path.exists(),
        "openpyxl_available": True,
        "corrupted_cells": 0,
        "examples": [],
        "error": "",
    }
    if not path.exists():
        return result
    try:
        import openpyxl  # type: ignore
    except Exception as exc:  # pragma: no cover
        result["openpyxl_available"] = False
        result["error"] = str(exc)
        return result

    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                for idx, cell in enumerate(row, start=1):
                    if not isinstance(cell, str):
                        continue
                    if not has_marker(cell):
                        continue
                    result["corrupted_cells"] += 1
                    if len(result["examples"]) < max_examples:
                        result["examples"].append(
                            {"sheet": ws.title, "column_index": idx, "value": cell[:240]}
                        )
        wb.close()
    except Exception as exc:
        result["error"] = str(exc)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repair", action="store_true")
    parser.add_argument("--examples", type=int, default=6)
    args = parser.parse_args()

    files = [
        Path("app/data/runtime/rag/tests_clean.jsonl"),
        Path("app/data/runtime/rag/tests_business_clean.jsonl"),
        Path("app/data/runtime/rag/packages_clean.jsonl"),
        Path("app/data/runtime/rag/packages_business_clean.jsonl"),
        Path("app/data/runtime/rag/branches_with_coordinates.jsonl"),
    ]
    excel_path = Path("app/data/sources/excel/SOURCES/analysis_file.xlsx")

    report: dict[str, Any] = {"scans_before": [], "repairs": [], "scans_after": [], "excel_scan": {}}

    for p in files:
        report["scans_before"].append(scan_jsonl(p, max_examples=args.examples))

    if args.repair:
        for p in files:
            report["repairs"].append(repair_jsonl(p))
        for p in files:
            report["scans_after"].append(scan_jsonl(p, max_examples=args.examples))

    report["excel_scan"] = scan_excel(excel_path, max_examples=args.examples)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

