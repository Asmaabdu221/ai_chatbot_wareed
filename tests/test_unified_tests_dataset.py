import json
from pathlib import Path


TESTS_PATH = Path("app/data/runtime/rag/tests_clean.jsonl")


def _load_rows() -> list[dict]:
    rows: list[dict] = []
    with TESTS_PATH.open("r", encoding="utf-8") as f:
        for raw in f:
            line = (raw or "").strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _as_text(value) -> str:
    if isinstance(value, (int, float)):
        return f"{value:g}"
    return str(value or "").strip()


def test_unified_tests_dataset_core_fields():
    assert TESTS_PATH.exists(), f"Missing unified dataset: {TESTS_PATH}"
    rows = _load_rows()
    assert len(rows) > 0, "Unified tests dataset is empty"

    # Arabic canonical name exists in at least one record.
    has_arabic_name = False
    has_price = False
    has_fasting = False
    has_sample_type = False

    for row in rows:
        name_ar = _as_text(
            row.get("canonical_name_ar")
            or row.get("test_name_ar")
            or row.get("title")
            or row.get("h1")
        )
        if name_ar and any("\u0600" <= ch <= "\u06FF" for ch in name_ar):
            has_arabic_name = True

        if _as_text(
            row.get("price")
            or row.get("price_raw")
            or row.get("price_number")
            or row.get("price_text")
            or row.get("excel_price")
        ):
            has_price = True

        if _as_text(row.get("fasting")):
            has_fasting = True

        if _as_text(row.get("sample_type")):
            has_sample_type = True

        if has_arabic_name and has_price and has_fasting and has_sample_type:
            break

    assert has_arabic_name, "No Arabic canonical test name found in unified dataset"
    assert has_price, "No usable price field found (price/price_raw/price_number/price_text/excel_price)"
    assert has_fasting, "No fasting field value found"
    assert has_sample_type, "No sample_type field value found"
