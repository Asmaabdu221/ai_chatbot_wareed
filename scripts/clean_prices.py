from __future__ import annotations

import argparse
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

DEFAULT_SOURCE_PATH = Path("app/data/sources/excel/praacise.xlsx")
DEFAULT_SHEET_NAME = "Sheet1"
DEFAULT_OUTPUT_PATH = Path("app/data/runtime/lookup/tests_price_index.json")
DEFAULT_QA_OUTPUT_PATH = Path("app/data/runtime/reports/prices_qa.json")
DEFAULT_CHUNKS_OUTPUT_PATH = Path("app/data/runtime/rag/prices_chunks.jsonl")
SPACE_RE = re.compile(r"\s+")
ARABIC_DIACRITICS_RE = re.compile(r"[\u064B-\u065F\u0670\u0640]")


def _clean_text(value: Any) -> str | None:
    if pd.isna(value):
        return None
    text = str(value)
    text = SPACE_RE.sub(" ", text.strip())
    return text if text else None


def _parse_price(value: Any) -> float | None:
    if pd.isna(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        return None
    text = text.replace(",", "")
    text = SPACE_RE.sub("", text)
    if not text:
        return None

    try:
        return float(text)
    except ValueError:
        return None


def normalize_key(text: str | None) -> str:
    if not text:
        return ""
    value = text.lower()
    value = ARABIC_DIACRITICS_RE.sub("", value).replace("ـ", "")
    value = (
        value.replace("أ", "ا")
        .replace("إ", "ا")
        .replace("آ", "ا")
        .replace("ى", "ي")
        .replace("ة", "ه")
    )
    value = "".join(ch if not unicodedata.category(ch).startswith("P") else " " for ch in value)
    value = SPACE_RE.sub(" ", value).strip()
    return value


def parse_prices_rows(
    source_path: Path, sheet_name: str
) -> tuple[str, int, list[str], list[dict[str, Any]], int]:
    df = pd.read_excel(source_path, sheet_name=sheet_name)
    cols = [str(c) for c in df.columns]

    ar_col = cols[0] if len(cols) > 0 else "arabic_name"
    en_col = cols[1] if len(cols) > 1 else "english_name"
    price_col = cols[2] if len(cols) > 2 else "price"

    records: list[dict[str, Any]] = []
    total_rows_scanned = 0
    for _, row in df.iterrows():
        total_rows_scanned += 1
        arabic_name = _clean_text(row[df.columns[0]]) if len(df.columns) > 0 else None
        english_name = _clean_text(row[df.columns[1]]) if len(df.columns) > 1 else None
        price = _parse_price(row[df.columns[2]]) if len(df.columns) > 2 else None

        # Drop rows where both Arabic and English names are empty.
        if not arabic_name and not english_name:
            continue

        records.append(
            {
                ar_col: arabic_name,
                en_col: english_name,
                price_col: price,
            }
        )

    return sheet_name, len(records), cols, records, total_rows_scanned


def build_price_index(records: list[dict[str, Any]], columns: list[str]) -> tuple[dict[str, Any], dict[str, int]]:
    ar_col = columns[0] if len(columns) > 0 else "arabic_name"
    en_col = columns[1] if len(columns) > 1 else "english_name"
    price_col = columns[2] if len(columns) > 2 else "price"

    deduped_map: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    deduped_count = 0

    for rec in records:
        name_ar = rec.get(ar_col)
        name_en = rec.get(en_col)
        price = rec.get(price_col)

        norm_ar = normalize_key(name_ar)
        norm_en = normalize_key(name_en)
        dedupe_key = norm_ar if norm_ar else norm_en
        if not dedupe_key:
            continue

        keys: list[str] = []
        if norm_ar:
            keys.append(norm_ar)
        if norm_en and norm_en not in keys:
            keys.append(norm_en)

        candidate = {
            "name_ar": name_ar,
            "name_en": name_en,
            "price": price,
            "keys": keys,
        }

        existing = deduped_map.get(dedupe_key)
        if existing is None:
            deduped_map[dedupe_key] = candidate
            order.append(dedupe_key)
            continue

        deduped_count += 1
        existing_price = existing.get("price")
        # Prefer non-null price; if both priced, keep first for stability.
        if existing_price is None and price is not None:
            deduped_map[dedupe_key] = candidate

    out_records: list[dict[str, Any]] = []
    for idx, key in enumerate(order, start=1):
        rec = deduped_map[key]
        out_records.append(
            {
                "id": f"price::{idx:04d}",
                "name_ar": rec.get("name_ar"),
                "name_en": rec.get("name_en"),
                "price": rec.get("price"),
                "keys": rec.get("keys") or [],
            }
        )

    payload = {
        "version": 1,
        "source_file": DEFAULT_SOURCE_PATH.as_posix(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "records": out_records,
    }
    stats = {
        "records_written": len(out_records),
        "deduped_count": deduped_count,
        "missing_price_count": sum(1 for r in out_records if r.get("price") is None),
    }
    return payload, stats


def write_json(data: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def write_jsonl(items: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def build_chunks(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for rec in records:
        name_ar = rec.get("name_ar")
        name_en = rec.get("name_en")
        price = rec.get("price")

        name_ar_text = name_ar if name_ar else "غير مذكور"
        name_en_text = name_en if name_en else "EN N/A"
        price_text = str(price) if price is not None else "غير متوفر"

        chunks.append(
            {
                "id": rec.get("id"),
                "text": f"اسم التحليل: {name_ar_text} ({name_en_text})\nالسعر: {price_text}",
                "metadata": {
                    "source": "prices",
                    "name_ar": name_ar,
                    "name_en": name_en,
                    "price": price,
                },
            }
        )
    return chunks


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Clean prices Excel rows and build lookup index")
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE_PATH,
        help=f"Path to prices Excel file (default: {DEFAULT_SOURCE_PATH})",
    )
    parser.add_argument(
        "--sheet",
        default=DEFAULT_SHEET_NAME,
        help=f"Worksheet name (default: {DEFAULT_SHEET_NAME})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=f"Path to output JSON file (default: {DEFAULT_OUTPUT_PATH})",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    sheet_name, row_count, columns, records, total_rows_scanned = parse_prices_rows(args.source, args.sheet)
    payload, stats = build_price_index(records, columns)
    write_json(payload, args.output)
    chunks = build_chunks(payload["records"])
    write_jsonl(chunks, DEFAULT_CHUNKS_OUTPUT_PATH)
    qa_payload = {
        "input_file": args.source.as_posix(),
        "lookup_output": args.output.as_posix(),
        "total_rows_scanned": total_rows_scanned,
        "records_written": stats["records_written"],
        "deduped_count": stats["deduped_count"],
        "missing_price_count": stats["missing_price_count"],
        "sample_records": payload["records"][:5],
    }
    write_json(qa_payload, DEFAULT_QA_OUTPUT_PATH)

    print(f"sheet name: {sheet_name}")
    print(f"row count: {row_count}")
    print(f"columns: {columns}")
    print(f"total_rows_scanned: {total_rows_scanned}")
    print(f"records_written: {stats['records_written']}")
    print(f"deduped_count: {stats['deduped_count']}")
    print(f"missing_price_count: {stats['missing_price_count']}")
    print(f"lookup_output: {args.output.as_posix()}")
    print(f"chunks_output: {DEFAULT_CHUNKS_OUTPUT_PATH.as_posix()}")
    print(f"qa_output: {DEFAULT_QA_OUTPUT_PATH.as_posix()}")


if __name__ == "__main__":
    main()
