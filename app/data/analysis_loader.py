"""
Analysis File Loader with Price Matching
=========================================
المصدر الوحيد للمعرفة: analysis_file.xlsx
دمج الأسعار من الملف القديم (knowledge_base_with_faq.json) باستخدام:
- Fuzzy Matching
- Levenshtein Distance
- Case-insensitive matching
- Arabic normalization

لا يتم اختراع أو تخمين أي أسعار.
"""

import json
import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from rapidfuzz import fuzz
from rapidfuzz.distance import Levenshtein

from app.utils.arabic_normalizer import normalize_for_matching

logger = logging.getLogger(__name__)

# Single source of truth
ANALYSIS_FILE_PATH = os.path.join(
    os.path.dirname(__file__),
    "analysis_file.xlsx"
)

# Old file with prices (for matching only - will be removed after migration)
OLD_PRICES_PATH = os.path.join(
    os.path.dirname(__file__),
    "knowledge_base_with_faq.json"
)

# Output: unified knowledge base (built from analysis_file.xlsx + matched prices)
RAG_KNOWLEDGE_PATH = os.path.join(
    os.path.dirname(__file__),
    "rag_knowledge_base.json"
)

# Column mapping: flexible for different Excel structures
COLUMN_MAPPING = {
    "اسم التحليل بالعربية": "analysis_name_ar",
    "اسم التحليل": "analysis_name_ar",
    "analysis_name_ar": "analysis_name_ar",
    "الاسم بالعربية": "analysis_name_ar",
    "Unnamed: 0": "analysis_name_en",
    "english_name": "analysis_name_en",
    "analysis_name_en": "analysis_name_en",
    "فائدة التحليل": "description",
    "description": "description",
    "التحاليل المكملة": "complementary_tests",
    "complementary_tests": "complementary_tests",
    "تحاليل قريبة": "related_tests",
    "related_tests": "related_tests",
    "تحاليل بديلة": "alternative_tests",
    "alternative_tests": "alternative_tests",
    "نوع العينة": "sample_type",
    "sample_type": "sample_type",
    "تصنيف التحليل": "category",
    "category": "category",
    "الأعراض": "symptoms",
    "symptoms": "symptoms",
    "التحضير قبل التحليل": "preparation",
    "preparation": "preparation",
}


def _load_json_robust(path: str) -> Optional[Dict]:
    """Load JSON; handle NaN/Infinity."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except Exception as e:
        logger.warning("Could not read %s: %s", path, e)
        return None
    text = re.sub(r":\s*NaN\b", ": null", text)
    text = re.sub(r":\s*-?Infinity\b", ": null", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning("Invalid JSON in %s: %s", path, e)
        return None


def _map_excel_row(row: Dict, df_columns: List[str]) -> Dict[str, Any]:
    """Map Excel row to standard schema."""
    result = {}
    for excel_col in df_columns:
        en_name = COLUMN_MAPPING.get(excel_col)
        if en_name:
            val = row.get(excel_col)
            if pd.notna(val) and str(val).strip():
                if isinstance(val, float) and val != int(val):
                    result[en_name] = val
                else:
                    result[en_name] = val
    return result


def _normalized_levenshtein_similarity(a: str, b: str) -> float:
    """Return similarity 0-100 based on Levenshtein (1 - normalized distance)."""
    na = normalize_for_matching(a)
    nb = normalize_for_matching(b)
    if not na or not nb:
        return 0.0
    dist = Levenshtein.distance(na, nb)
    max_len = max(len(na), len(nb))
    if max_len == 0:
        return 100.0
    sim = 1 - (dist / max_len)
    return max(0, min(100, sim * 100))


def _fuzzy_score(a: str, b: str) -> float:
    """Combined fuzzy + Levenshtein score (0-100)."""
    na = normalize_for_matching(a)
    nb = normalize_for_matching(b)
    if not na or not nb:
        return 0.0
    # Token sort ratio handles word order
    f1 = fuzz.ratio(na, nb)
    f2 = fuzz.partial_ratio(na, nb)
    lev = _normalized_levenshtein_similarity(a, b)
    return max(f1, f2, lev)


def _find_best_price_match(
    name_ar: str,
    price_records: List[Dict],
    min_score: float = 75.0
) -> Optional[Tuple[Dict, float]]:
    """
    Find best matching record from old prices by analysis name.
    Returns (record, score) or None if no match above min_score.
    """
    if not name_ar or not price_records:
        return None
    best = None
    best_score = 0.0
    for rec in price_records:
        old_name = rec.get("analysis_name_ar") or rec.get("الاسم") or ""
        if not old_name:
            continue
        price = rec.get("price")
        if price is None or (isinstance(price, float) and (price != price)):  # NaN
            continue
        score = _fuzzy_score(name_ar, old_name)
        if score >= min_score and score > best_score:
            best_score = score
            best = rec
    if best and best_score >= min_score:
        return (best, best_score)
    return None


def load_analysis_file_with_prices() -> Tuple[List[Dict], Dict]:
    """
    Load analysis_file.xlsx as sole source, merge prices from old file.
    
    Returns:
        (list of test records, metadata dict)
    """
    if not os.path.exists(ANALYSIS_FILE_PATH):
        raise FileNotFoundError(
            f"analysis_file.xlsx not found at {ANALYSIS_FILE_PATH}. "
            "Please add the file and run the build script."
        )
    
    df = pd.read_excel(ANALYSIS_FILE_PATH)
    df = df.where(pd.notna(df), None)
    columns = df.columns.tolist()
    
    # Build price lookup from old file
    price_records = []
    if os.path.exists(OLD_PRICES_PATH):
        old_data = _load_json_robust(OLD_PRICES_PATH)
        if old_data:
            price_records = old_data.get("tests", [])
            logger.info("Loaded %d records from old prices file for matching", len(price_records))
    
    # Map required: at least analysis_name_ar
    name_col = None
    for c in columns:
        if str(c).strip() in ("اسم التحليل بالعربية", "اسم التحليل", "analysis_name_ar", "الاسم بالعربية"):
            name_col = c
            break
    if not name_col:
        # Fallback: first column as name
        name_col = columns[0] if columns else None
    
    tests = []
    matched_count = 0
    for _, row in df.iterrows():
        rec = _map_excel_row(row.to_dict(), columns)
        name_ar = rec.get("analysis_name_ar") or (str(row.get(name_col, "")) if name_col else "")
        if not name_ar or (isinstance(name_ar, float) and (name_ar != name_ar or pd.isna(name_ar))):
            continue
        name_ar = str(name_ar).strip()
        rec["analysis_name_ar"] = name_ar
        
        # Price matching: only merge when we find a match
        match_result = _find_best_price_match(name_ar, price_records, min_score=75.0)
        if match_result:
            old_rec, score = match_result
            price = old_rec.get("price")
            if price is not None:
                rec["price"] = float(price) if isinstance(price, (int, float)) else None
                rec["price_match_confidence"] = round(score, 2)
                matched_count += 1
        # If no match: do NOT add price. No guessing.
        
        # Ensure standard fields exist
        for k in ("description", "category", "symptoms", "preparation", "sample_type",
                  "complementary_tests", "related_tests", "alternative_tests"):
            if k not in rec:
                rec[k] = None
        
        tests.append(rec)
    
    metadata = {
        "title": "Wareed Medical Laboratory - RAG Knowledge Base",
        "description": "Single source: analysis_file.xlsx with matched prices",
        "version": "3.0.0",
        "created_at": datetime.now().isoformat(),
        "total_tests": len(tests),
        "source_file": "analysis_file.xlsx",
        "prices_matched": matched_count,
        "language": "ar",
        "secondary_language": "en",
    }
    
    logger.info(
        "Loaded %d tests from analysis_file.xlsx, matched %d prices",
        len(tests), matched_count
    )
    return tests, metadata


def build_rag_knowledge_base() -> str:
    """
    Build RAG knowledge base from analysis_file.xlsx and save to rag_knowledge_base.json.
    Returns path to output file.
    """
    tests, metadata = load_analysis_file_with_prices()
    data = {
        "metadata": metadata,
        "tests": tests,
        "faqs": []  # No FAQs - single source only
    }
    with open(RAG_KNOWLEDGE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info("Saved RAG knowledge base to %s", RAG_KNOWLEDGE_PATH)
    return RAG_KNOWLEDGE_PATH
