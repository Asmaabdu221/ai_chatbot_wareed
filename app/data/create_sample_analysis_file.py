"""
Create Sample analysis_file.xlsx from Existing Data
====================================================
للاستخدام عند عدم وجود analysis_file.xlsx - ينشئ نسخة من البيانات الحالية.
للتشغيل: python -m app.data.create_sample_analysis_file
"""

import json
import os
import re
import sys

import pandas as pd

DATA_DIR = os.path.dirname(__file__)
OLD_KB = os.path.join(DATA_DIR, "knowledge_base_with_faq.json")
OUTPUT = os.path.join(DATA_DIR, "analysis_file.xlsx")


def _load_json(path):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    text = re.sub(r":\s*NaN\b", ": null", text)
    text = re.sub(r":\s*-?Infinity\b", ": null", text)
    return json.loads(text)


def main():
    data = _load_json(OLD_KB)
    if not data:
        print("knowledge_base_with_faq.json not found. Cannot create sample.")
        sys.exit(1)
    tests = data.get("tests", [])
    if not tests:
        print("No tests in knowledge base.")
        sys.exit(1)
    # Map to Excel columns (Arabic)
    rows = []
    for t in tests:
        rows.append({
            "اسم التحليل بالعربية": t.get("analysis_name_ar"),
            "Unnamed: 0": t.get("analysis_name_en"),
            "فائدة التحليل": t.get("description"),
            "التحاليل المكملة": t.get("complementary_tests"),
            "تحاليل قريبة": t.get("related_tests"),
            "تحاليل بديلة": t.get("alternative_tests"),
            "نوع العينة": t.get("sample_type"),
            "تصنيف التحليل": t.get("category"),
            "الأعراض": t.get("symptoms"),
            "التحضير قبل التحليل": t.get("preparation"),
        })
    df = pd.DataFrame(rows)
    df.to_excel(OUTPUT, index=False)
    print(f"Created {OUTPUT} with {len(rows)} tests")
    print("You can now run: python -m app.data.build_rag_system")


if __name__ == "__main__":
    main()
