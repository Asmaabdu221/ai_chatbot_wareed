from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.knowledge_engine.excel_cleaner import clean_packages_excel


def test_clean_packages_excel_drops_headers_sections_and_parses_prices(tmp_path: Path) -> None:
    xlsx = tmp_path / "PAKAGE1.xlsx"
    # Emulates visual-layout sheet: embedded header row, section row, and merged-cell style blanks.
    df = pd.DataFrame(
        [
            {"A": "اسم الباقه", "B": "وصف الباقه", "C": "سعر الباقه"},
            {"A": "الصحة العامة", "B": "", "C": ""},
            {"A": "باقة A", "B": "وصف A\nالسعر: 200 ريال", "C": ""},
            {"A": "باقة B\nتفاصيل", "B": "وصف B", "C": "1,250"},
            {"A": "باقة C", "B": "", "C": ""},
            {"A": "", "B": "اختبار CBC", "C": "300 ريال"},
        ]
    )
    df.to_excel(xlsx, index=False)

    cleaned = clean_packages_excel(xlsx)
    assert list(cleaned.columns) == ["name", "description_long", "price"]
    assert len(cleaned) == 3

    # Header and section rows must be removed.
    assert not any("اسم الباق" in str(v) for v in cleaned["name"])
    assert not any("الصحة العامة" in str(v) for v in cleaned["name"])

    # Prices from column and description fallback.
    rows = cleaned.to_dict(orient="records")
    by_name = {r["name"]: r for r in rows}
    assert by_name["باقة A"]["price"] == 200.0
    assert by_name["باقة B\nتفاصيل"]["price"] == 1250.0
    assert by_name["باقة C"]["price"] == 300.0

