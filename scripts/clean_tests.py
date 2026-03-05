from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

DEFAULT_SOURCE_PATH = Path("app/data/sources/excel/analyses_with_prices.xlsx")
DEFAULT_SHEET_NAME = "Sheet1"
DEFAULT_OUTPUT_PATH = Path("app/data/runtime/rag/tests_clean.jsonl")
DEFAULT_CHUNKS_OUTPUT_PATH = Path("app/data/runtime/rag/tests_chunks.jsonl")
DEFAULT_QA_OUTPUT_PATH = Path("app/data/runtime/reports/tests_qa.json")
SPACE_RE = re.compile(r"\s+")
CODE_PREFIX_RE = re.compile(r"^\s*(\d+)\s*-\s*(.+)$")
CATEGORY_NORM_MAP = {
    "الدم والتحثر": "الدم والتخثر",
}


def _normalize_value(value: Any) -> Any:
    if pd.isna(value):
        return None

    if isinstance(value, str):
        cleaned = SPACE_RE.sub(" ", value.strip())
        return cleaned if cleaned else None

    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            return value

    return value


def _to_float_or_none(value: Any) -> float | None:
    normalized = _normalize_value(value)
    if normalized is None:
        return None

    if isinstance(normalized, (int, float)):
        return float(normalized)

    text = str(normalized).replace(",", "").strip()
    text = SPACE_RE.sub("", text)
    if not text:
        return None

    try:
        return float(text)
    except ValueError:
        return None


def _canonical_name(row: dict[str, Any]) -> str | None:
    analysis_name = row.get("analysis_name")
    if isinstance(analysis_name, str):
        analysis_name = SPACE_RE.sub(" ", analysis_name.strip())
    if analysis_name:
        return analysis_name

    analysis_name_clean = row.get("analysis_name_clean")
    if isinstance(analysis_name_clean, str):
        analysis_name_clean = SPACE_RE.sub(" ", analysis_name_clean.strip())
    if analysis_name_clean:
        return analysis_name_clean

    return row.get("اسم التحليل بالعربية")


def _extract_code_and_clean_name(canonical_name: str | None) -> tuple[int | None, str]:
    if canonical_name is None:
        return None, ""

    value = str(canonical_name).strip()
    code: int | None = None
    match = CODE_PREFIX_RE.match(value)
    if match:
        code = int(match.group(1))
        value = match.group(2).strip()

    # Remove trailing markers like "-{Q}", "{Q}", or any "{...}" at the end.
    value = re.sub(r"\s*(?:-\s*)?\{[^{}]*\}\s*$", "", value)
    value = value.rstrip(" -").strip()
    return code, value


def parse_tests_rows(source_path: Path, sheet_name: str) -> list[dict[str, Any]]:
    df = pd.read_excel(source_path, sheet_name=sheet_name)

    if "Unnamed: 0" in df.columns and "english_name" in df.columns:
        unnamed = df["Unnamed: 0"].fillna("").astype(str).str.strip()
        english = df["english_name"].fillna("").astype(str).str.strip()
        if unnamed.equals(english):
            df = df.drop(columns=["Unnamed: 0"])

    records: list[dict[str, Any]] = []
    for idx, (_, row) in enumerate(df.iterrows(), start=1):
        rec: dict[str, Any] = {}
        for col in df.columns:
            rec[str(col)] = _normalize_value(row[col])

        canonical_name = _canonical_name(rec)
        code, canonical_name_clean = _extract_code_and_clean_name(canonical_name)
        category = rec.get("تصنيف التحليل")
        category_norm = CATEGORY_NORM_MAP.get(category, category)

        records.append(
            {
                "source": "tests",
                "id": f"tests::{idx:04d}",
                "canonical_ar": rec.get("اسم التحليل بالعربية"),
                "canonical_en": rec.get("english_name"),
                "canonical_name": canonical_name,
                "canonical_name_clean": canonical_name_clean,
                "code": code,
                "category": category,
                "category_norm": category_norm,
                "sample_type": rec.get("نوع العينة"),
                "benefit": rec.get("فائدة التحليل"),
                "symptoms": rec.get("الأعراض"),
                "preparation": rec.get("التحضير قبل التحليل"),
                "complementary_tests": rec.get("التحاليل المكملة"),
                "related_tests": rec.get("تحاليل قريبة"),
                "alternative_tests": rec.get("تحاليل بديلة"),
                "price": _to_float_or_none(rec.get("price")),
                "match_score": _to_float_or_none(rec.get("match_score")),
            }
        )

    return records


def write_jsonl(records: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_json(data: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def read_jsonl(input_path: Path) -> list[dict[str, Any]]:
    if not input_path.exists():
        return []
    items: list[dict[str, Any]] = []
    with input_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            items.append(json.loads(line))
    return items


def _text_or_default(value: Any, default: str = "غير مذكور") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def build_chunks(clean_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for rec in clean_records:
        canonical_ar = _text_or_default(rec.get("canonical_ar"))
        canonical_en_raw = rec.get("canonical_en")
        if canonical_en_raw is None or str(canonical_en_raw).strip() == "":
            canonical_en_display = "EN N/A"
        else:
            canonical_en_text = str(canonical_en_raw).strip()
            canonical_en_display = (
                canonical_en_text
                if canonical_en_text.startswith("(") or "(" in canonical_en_text
                else f"({canonical_en_text})"
            )

        category = _text_or_default(rec.get("category_norm") or rec.get("category"))
        sample_type = _text_or_default(rec.get("sample_type"))
        benefit = _text_or_default(rec.get("benefit"))
        symptoms = _text_or_default(rec.get("symptoms"))
        preparation = _text_or_default(rec.get("preparation"))
        complementary_tests = _text_or_default(rec.get("complementary_tests"))
        related_tests = _text_or_default(rec.get("related_tests"))
        alternative_tests = _text_or_default(rec.get("alternative_tests"))
        price = rec.get("price")
        price_text = "غير متوفر" if price is None else str(price)

        text = (
            f"اسم التحليل: {canonical_ar} {canonical_en_display}\n"
            f"التصنيف: {category}\n"
            f"نوع العينة: {sample_type}\n"
            f"فائدة التحليل: {benefit}\n"
            f"الأعراض المرتبطة: {symptoms}\n"
            f"التحضير قبل التحليل: {preparation}\n"
            f"تحاليل مكملة: {complementary_tests}\n"
            f"تحاليل قريبة: {related_tests}\n"
            f"تحاليل بديلة: {alternative_tests}\n"
            f"السعر: {price_text}"
        )
        chunks.append(
            {
                "id": rec.get("id"),
                "text": text,
                "metadata": {
                    "source": "tests",
                    "canonical_ar": rec.get("canonical_ar"),
                    "canonical_en": rec.get("canonical_en"),
                    "category": rec.get("category"),
                    "category_norm": rec.get("category_norm"),
                    "code": rec.get("code"),
                    "canonical_name_clean": rec.get("canonical_name_clean"),
                    "sample_type": rec.get("sample_type"),
                    "price": rec.get("price"),
                },
            }
        )
    return chunks


def build_qa_report(
    source_path: Path,
    clean_output_path: Path,
    chunks_output_path: Path,
    clean_records: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
) -> dict[str, Any]:
    unique_raw_categories: list[str] = []
    seen_raw_categories: set[str] = set()
    unique_norm_categories: list[str] = []
    seen_norm_categories: set[str] = set()
    missing_price_count = 0
    missing_benefit_count = 0
    missing_symptoms_count = 0
    missing_preparation_count = 0

    for rec in clean_records:
        raw_category = rec.get("category")
        norm_category = rec.get("category_norm") or raw_category
        if raw_category and raw_category not in seen_raw_categories:
            seen_raw_categories.add(raw_category)
            unique_raw_categories.append(raw_category)
        if norm_category and norm_category not in seen_norm_categories:
            seen_norm_categories.add(norm_category)
            unique_norm_categories.append(norm_category)
        if rec.get("price") is None:
            missing_price_count += 1
        if not rec.get("benefit"):
            missing_benefit_count += 1
        if not rec.get("symptoms"):
            missing_symptoms_count += 1
        if not rec.get("preparation"):
            missing_preparation_count += 1

    return {
        "input_file": source_path.as_posix(),
        "clean_output": clean_output_path.as_posix(),
        "chunks_output": chunks_output_path.as_posix(),
        "total_rows_scanned": len(clean_records),
        "records_written": len(clean_records),
        "chunks_written": len(chunks),
        "missing_price_count": missing_price_count,
        "unique_categories_count": len(unique_norm_categories),
        "unique_categories_sample": unique_norm_categories[:15],
        "unique_raw_categories_count": len(unique_raw_categories),
        "unique_category_norm_count": len(unique_norm_categories),
        "missing_benefit_count": missing_benefit_count,
        "missing_symptoms_count": missing_symptoms_count,
        "missing_preparation_count": missing_preparation_count,
        "sample_clean_records": clean_records[:3],
        "sample_chunks": chunks[:3],
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Clean tests sheet and export canonical JSONL")
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE_PATH,
        help=f"Path to Excel file (default: {DEFAULT_SOURCE_PATH})",
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
        help=f"Path to output JSONL file (default: {DEFAULT_OUTPUT_PATH})",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    records = parse_tests_rows(args.source, args.sheet)
    write_jsonl(records, args.output)
    clean_records = read_jsonl(args.output)
    chunks = build_chunks(clean_records)
    write_jsonl(chunks, DEFAULT_CHUNKS_OUTPUT_PATH)
    qa_report = build_qa_report(
        source_path=args.source,
        clean_output_path=args.output,
        chunks_output_path=DEFAULT_CHUNKS_OUTPUT_PATH,
        clean_records=clean_records,
        chunks=chunks,
    )
    write_json(qa_report, DEFAULT_QA_OUTPUT_PATH)

    missing_price_count = sum(1 for r in records if r.get("price") is None)
    missing_canonical_name_count = sum(1 for r in records if not r.get("canonical_name"))
    missing_canonical_ar_count = sum(1 for r in records if not r.get("canonical_ar"))

    print(f"total_rows_scanned: {len(records)}")
    print(f"records_written: {len(records)}")
    print(f"missing_price_count: {missing_price_count}")
    print(f"missing_canonical_name_count: {missing_canonical_name_count}")
    print(f"missing_canonical_ar_count: {missing_canonical_ar_count}")
    print(f"chunks_written: {len(chunks)}")
    for chunk in chunks[:3]:
        print(chunk)
    print(f"qa_report_output: {DEFAULT_QA_OUTPUT_PATH.as_posix()}")
    print(f"unique_categories_count: {qa_report['unique_categories_count']}")
    print(f"unique_raw_categories_count: {qa_report['unique_raw_categories_count']}")
    print(f"unique_category_norm_count: {qa_report['unique_category_norm_count']}")
    print(f"missing_benefit_count: {qa_report['missing_benefit_count']}")
    print(f"missing_symptoms_count: {qa_report['missing_symptoms_count']}")
    print(f"missing_preparation_count: {qa_report['missing_preparation_count']}")
    for record in records[:5]:
        print(
            f"{record.get('canonical_name')} -> {record.get('canonical_name_clean')} + code={record.get('code')}"
        )
        print(f"{record.get('category')} -> {record.get('category_norm')}")


if __name__ == "__main__":
    main()
