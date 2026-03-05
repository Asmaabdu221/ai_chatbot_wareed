from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd


def _normalize_arabic_light(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[\u064B-\u065F\u0670]", "", text)
    text = (
        text.replace("أ", "ا")
        .replace("إ", "ا")
        .replace("آ", "ا")
        .replace("ى", "ي")
        .replace("ئ", "ي")
        .replace("ؤ", "و")
        .replace("ة", "ه")
    )
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _parse_price(value: Any) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    match = re.search(r"\d+(?:\.\d+)?", text.replace(",", ""))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _extract_price_from_text(text: str) -> float | None:
    value = str(text or "").translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    patterns = [
        r"السعر\s*[:：]?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*ريال",
        r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*ريال",
    ]
    for pattern in patterns:
        m = re.search(pattern, value)
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                continue
    return None


def _looks_like_header(value: Any) -> bool:
    norm = _normalize_arabic_light(value)
    if not norm:
        return False
    header_markers = [
        _normalize_arabic_light("اسم الباقه"),
        _normalize_arabic_light("اسم الباقة"),
        _normalize_arabic_light("وصف الباقه"),
        _normalize_arabic_light("وصف الباقة"),
        _normalize_arabic_light("سعر الباقه"),
        _normalize_arabic_light("سعر الباقة"),
    ]
    return any(marker in norm for marker in header_markers)


def clean_packages_excel(input_path: Path) -> pd.DataFrame:
    df_raw = pd.read_excel(input_path, sheet_name=0)
    if df_raw.empty:
        return pd.DataFrame(columns=["name", "description_long", "price"])

    cols = list(df_raw.columns)
    col_name = cols[0] if len(cols) > 0 else None
    col_desc = cols[1] if len(cols) > 1 else None
    col_price = cols[2] if len(cols) > 2 else None
    if not (col_name and col_desc and col_price):
        return pd.DataFrame(columns=["name", "description_long", "price"])

    # Preserve raw content to identify section/header rows before forward-fill.
    raw = df_raw[[col_name, col_desc, col_price]].copy()
    raw = raw.where(pd.notna(raw), "")

    df = df_raw[[col_name, col_desc, col_price]].copy()
    df[[col_name, col_desc, col_price]] = df[[col_name, col_desc, col_price]].ffill()
    df = df.where(pd.notna(df), "")

    cleaned_rows: list[dict[str, Any]] = []
    for idx, row in df.iterrows():
        raw_name = str(raw.at[idx, col_name]).strip()
        raw_desc = str(raw.at[idx, col_desc]).strip()
        raw_price = str(raw.at[idx, col_price]).strip()

        # Drop embedded header rows.
        if _looks_like_header(raw_name) or _looks_like_header(raw_desc) or _looks_like_header(raw_price):
            continue

        # Drop section rows (single filled name cell, no desc, no price).
        raw_filled = sum(1 for x in [raw_name, raw_desc, raw_price] if str(x).strip())
        if raw_filled == 1 and raw_name and not raw_desc and not raw_price:
            continue

        name = str(row[col_name]).strip()
        description_long = str(row[col_desc]).strip()
        price = _parse_price(row[col_price])
        if price is None:
            price = _extract_price_from_text(description_long)

        if not name or not description_long:
            continue

        cleaned_rows.append(
            {
                "name": name,
                "description_long": description_long,
                "price": price,
            }
        )

    return pd.DataFrame(cleaned_rows, columns=["name", "description_long", "price"])

