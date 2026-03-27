"""Deterministic runtime resolver for package queries.

Rebuilt to use ONLY packages_clean.jsonl as the active runtime source of truth.
Matching is corpus-driven from package_name/category/descriptions in the JSONL.
"""

from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID

from app.services.runtime.selection_state import save_selection_state
from app.services.runtime.text_normalizer import normalize_arabic

PACKAGES_JSONL_PATH = Path("app/data/runtime/rag/packages_clean.jsonl")

_GENERAL_HINTS = (
    "Ø¨Ø§Ù‚Ø§Øª",
    "Ø¨Ø§Ù‚Ø§ØªÙƒÙ…",
    "Ø¹Ù†Ø¯ÙƒÙ… Ø¨Ø§Ù‚Ø§Øª",
    "ÙˆØ´ Ø¹Ù†Ø¯ÙƒÙ… Ø¨Ø§Ù‚Ø§Øª",
    "Ø§ÙŠØ´ Ø¹Ù†Ø¯ÙƒÙ… Ø¨Ø§Ù‚Ø§Øª",
    "Ø§Ù„Ø¨Ø§Ù‚Ø§Øª Ø§Ù„Ù…ØªÙˆÙØ±Ù‡",
    "Ø§Ù„Ø¨Ø§Ù‚Ø§Øª Ø§Ù„Ù…ØªØ§Ø­Ø©",
    "ÙˆØ´ Ø§Ù„Ø¨Ø§Ù‚Ø§Øª",
    "Ø§ÙŠØ´ Ø§Ù„Ø¨Ø§Ù‚Ø§Øª",
    "Ø§ÙŠØ´ Ø§Ù„Ø¨Ø§Ù‚Ø§Øª Ø§Ù„Ù…ØªÙˆÙØ±Ù‡",
    "Ù…Ø§ Ù‡ÙŠ Ø§Ù„Ø¨Ø§Ù‚Ø§Øª",
    "Ø§Ù„Ø¨Ø±Ø§Ù…Ø¬",
    "packages",
    "package list",
)

_GENERAL_LISTING_HINTS = (
    "ÙˆØ´ Ø§Ù„Ø¨Ø§Ù‚Ø§Øª",
    "Ø§ÙŠØ´ Ø§Ù„Ø¨Ø§Ù‚Ø§Øª",
    "Ù…Ø§Ù‡ÙŠ Ø§Ù„Ø¨Ø§Ù‚Ø§Øª",
    "Ù…Ø§ Ù‡ÙŠ Ø§Ù„Ø¨Ø§Ù‚Ø§Øª",
    "Ø§Ù†ÙˆØ§Ø¹ Ø§Ù„Ø¨Ø§Ù‚Ø§Øª",
    "Ø§Ù„Ø¨Ø§Ù‚Ø§Øª Ø§Ù„Ù…ØªÙˆÙØ±Ø©",
    "Ø§Ù„Ø¨Ø§Ù‚Ø§Øª Ø§Ù„Ù…ØªØ§Ø­Ø©",
    "Ø§Ù„Ø¨Ø§Ù‚Ø§Øª Ø§Ù„Ù„ÙŠ Ø¹Ù†Ø¯ÙƒÙ…",
    "Ø¹Ù†Ø¯ÙƒÙ… Ø¨Ø§Ù‚Ø§Øª",
)

_PRICE_HINTS = (
    "ÙƒÙ… Ø³Ø¹Ø±",
    "ÙƒÙ… Ø§Ø³Ø¹Ø§Ø±",
    "Ø³Ø¹Ø±",
    "Ø§Ø³Ø¹Ø§Ø±",
    "Ø¨ÙƒÙ…",
    "ÙƒÙ… ØªÙƒÙ„Ù",
    "ØªÙƒÙ„Ù",
    "ØªÙƒÙ„ÙØ©",
    "price",
    "cost",
)

_DETAIL_HINTS = (
    "ÙˆØ´ ØªØ´Ù…Ù„",
    "Ø§ÙŠØ´ ØªØ´Ù…Ù„",
    "ÙˆØ´ ÙÙŠÙ‡Ø§",
    "Ø§ÙŠØ´ ÙÙŠÙ‡Ø§",
    "ØªÙØ§ØµÙŠÙ„",
    "Ù…Ø­ØªÙˆÙ‰",
    "contains",
    "details",
    "what does it include",
    "include",
)

_CATEGORY_HINTS: dict[str, tuple[str, ...]] = {
    "Ø§Ù„Ø¨Ø§Ù‚Ø§Øª Ø§Ù„Ù…ØªØ®ØµØµØ©": ("Ø±Ù…Ø¶Ø§Ù†", "Ù…ØªØ®ØµØµÙ‡", "Ù…ØªØ®ØµØµØ©", "specialized"),
    "Ø§Ù„Ø¨Ø§Ù‚Ø§Øª Ø§Ù„Ø¬ÙŠÙ†ÙŠØ© Ø§Ù„ØªØ´Ø®ÙŠØµÙŠØ©": ("Ø¬ÙŠÙ†ÙŠ", "ÙˆØ±Ø§Ø«ÙŠ", "ØªØ´Ø®ÙŠØµÙŠ", "diagnostic genetic"),
    "Ø§Ù„Ø¨Ø§Ù‚Ø§Øª Ø§Ù„Ø¬ÙŠÙ†ÙŠØ© Ø§Ù„ÙˆÙ‚Ø§Ø¦ÙŠØ©": ("Ø¬ÙŠÙ†ÙŠ", "ÙˆØ±Ø§Ø«ÙŠ", "ÙˆÙ‚Ø§Ø¦ÙŠ", "preventive genetic"),
    "Ø§Ù„ØªØ­Ø§Ù„ÙŠÙ„ Ø§Ù„Ù…Ø®Ø¨Ø±ÙŠØ© Ø§Ù„ÙØ±Ø¯ÙŠØ©": ("ØªØ­Ø§Ù„ÙŠÙ„ ÙØ±Ø¯ÙŠÙ‡", "ØªØ­Ø§Ù„ÙŠÙ„ ÙØ±Ø¯ÙŠØ©", "single test", "individual tests"),
    "Ø§Ù„ØªØ­Ø§Ù„ÙŠÙ„ Ø§Ù„Ø°Ø§ØªÙŠØ©": ("Ø°Ø§ØªÙŠ", "Ø°Ø§ØªÙŠÙ‡", "self collection", "home collection"),
    "Ø§Ù„ØªØ­Ø§Ù„ÙŠÙ„ Ø§Ù„Ø¬ÙŠÙ†ÙŠØ©": ("ØªØ­Ø§Ù„ÙŠÙ„ Ø¬ÙŠÙ†ÙŠÙ‡", "ØªØ­Ø§Ù„ÙŠÙ„ Ø¬ÙŠÙ†ÙŠØ©", "genetic tests"),
}

_PRICE_NOT_AVAILABLE = "Ø³Ø¹Ø± Ù‡Ø°Ù‡ Ø§Ù„Ø¨Ø§Ù‚Ø© ØºÙŠØ± Ù…ØªÙˆÙØ± Ø­Ø§Ù„ÙŠÙ‹Ø§ ÙÙŠ Ø§Ù„Ø¨ÙŠØ§Ù†Ø§Øª Ø§Ù„Ø­Ø§Ù„ÙŠØ©."
_PACKAGE_NOT_FOUND = "Ù…Ø§ Ù‚Ø¯Ø±Øª Ø£Ø­Ø¯Ø¯ Ø¨Ø§Ù‚Ø© Ù…Ø­Ø¯Ø¯Ø© Ù…Ù† Ø³Ø¤Ø§Ù„Ùƒ. Ø§ÙƒØªØ¨ Ø§Ø³Ù… Ø§Ù„Ø¨Ø§Ù‚Ø© Ø¨Ø´ÙƒÙ„ Ø£ÙˆØ¶Ø­."

_STOPWORDS = {
    "Ø¨Ø§Ù‚Ù‡", "Ø¨Ø§Ù‚Ø©", "Ø¨Ø§Ù‚Ø§Øª", "ØªØ­Ù„ÙŠÙ„", "ØªØ­Ø§Ù„ÙŠÙ„", "ÙØ­Øµ", "ØªÙØ§ØµÙŠÙ„", "Ø§Ù„ØªØ­Ø§Ù„ÙŠÙ„",
    "Ø§Ø¨ÙŠ", "Ø§Ø¨ØºÙ‰", "Ø§Ø±ÙŠØ¯", "Ø¨Ø¯ÙŠ", "Ù…Ø­ØªØ§Ø¬", "Ø§Ø­ØªØ§Ø¬", "Ø¹Ù†Ø¯ÙŠ", "Ø´ÙŠØ¡", "Ø´ÙŠ", "Ø§Ø¨ÙŠÙ‡Ø§",
    "ÙƒÙ…", "Ø³Ø¹Ø±", "Ø§Ø³Ø¹Ø§Ø±", "Ø¨ÙƒÙ…", "ÙˆØ´", "Ø§ÙŠØ´", "Ù…Ø§", "Ù…Ø§Ù‡Ùˆ", "Ù‡Ùˆ", "Ù‡ÙŠ", "ÙÙŠ", "Ø¹Ù†",
    "Ù„", "Ù„Ù„", "Ø¹Ù„Ù‰", "Ù…Ù†", "Ù…Ø¹", "Ø§Ù„Ù‰", "Ø§Ùˆ", "Ùˆ", "Ø§Ùˆ", "Ø¨Ø¹Ø¯", "Ù‚Ø¨Ù„", "Ù‡Ø°Ù‡", "Ù‡Ø°Ø§",
    "package", "packages", "price", "cost", "details", "detail", "include", "includes",
    "the", "a", "an", "for", "of", "to", "and", "or",
}

_GENERIC_LOW_SIGNAL = {
    "ØµØ­Ù‡", "ØµØ­Ø©", "ØªØ­Ø§Ù„ÙŠÙ„", "ØªØ­Ù„ÙŠÙ„", "ÙØ­Øµ", "ÙØ­ÙˆØµØ§Øª", "Ø´Ø§Ù…Ù„Ù‡", "Ø´Ø§Ù…Ù„Ø©", "Ù…ØªØ®ØµØµÙ‡", "Ù…ØªØ®ØµØµØ©",
    "Ù…ØªØ§Ø¨Ø¹Ù‡", "Ù…ØªØ§Ø¨Ø¹Ø©", "Ø§Ù„ÙƒØ´Ù", "Ø§Ù„Ù…Ø¨ÙƒØ±", "ØªÙØ§ØµÙŠÙ„", "Ø¨Ø§Ù‚Ù‡", "Ø¨Ø§Ù‚Ø©", "package", "packages",
    "test", "tests",
}

_STRONG_KEYWORDS = {
    "ØºØ¯Ù‡", "Ø¯Ø±Ù‚ÙŠÙ‡", "Ø¯Ø±Ù‚ÙŠØ©", "thyroid",
    "Ø³ÙƒØ±ÙŠ", "Ø³ÙƒØ±", "glucose", "diabetes", "diabetic",
    "Ø´Ø¹Ø±", "hair", "ØªØ³Ø§Ù‚Ø·", "alopecia",
    "ÙÙŠØªØ§Ù…ÙŠÙ†", "ÙÙŠØªØ§Ù…ÙŠÙ†Ø§Øª", "vitamin", "vitamins",
    "Ø­Ø¯ÙŠØ¯", "iron", "ÙÙ‚Ø±", "Ø§Ù†ÙŠÙ…ÙŠØ§", "anemia", "anaemia",
    "Ù‡Ø±Ù…ÙˆÙ†", "Ù‡Ø±Ù…ÙˆÙ†Ø§Øª", "hormone", "hormonal",
    "Ø§Ø·ÙØ§Ù„", "Ø·ÙÙ„", "children", "kids", "child",
    "Ø±Ø¬Ø§Ù„", "men", "male", "man",
    "Ù†Ø³Ø§Ø¡", "Ù…Ø±Ø§Ù‡", "Ù…Ø±Ø£Ø©", "woman", "women", "female",
    "Ø±Ù…Ø¶Ø§Ù†", "ramadan",
    "Ø§ÙƒØªØ¦Ø§Ø¨", "depression",
    "ØµØ¯Ø§Ø¹", "migraine", "headache",
    "Ø¹Ø¸Ø§Ù…", "bone", "bones",
    "ÙƒØ¨Ø¯", "Ø§Ù„ÙƒØ¨Ø¯", "liver",
    "ÙƒÙ„Ù‰", "Ø§Ù„ÙƒÙ„ÙŠ", "kidney", "renal",
    "Ø­Ø³Ø§Ø³ÙŠÙ‡", "Ø­Ø³Ø§Ø³ÙŠØ©", "allergy", "allergies",
    "Ù‚Ù…Ø­", "Ø¬Ù„ÙˆØªÙŠÙ†", "gluten", "wheat",
    "Ø§ÙˆØ±Ø§Ù…", "Ø³Ø±Ø·Ø§Ù†", "tumor", "tumour", "cancer",
    "Ù…Ø¹Ø¯ÙŠÙ‡", "Ù…Ø¹Ø¯ÙŠØ©", "pcr", "std", "infection", "infectious",
    "Ù‚ÙˆÙ„ÙˆÙ†", "Ù‡Ø¶Ù…ÙŠ", "colon", "digestive", "gastro",
    "ØªÙƒÙ…ÙŠÙ…", "ÙƒÙ…ÙŠÙ…", "sleeve",
    "Ù…ÙˆÙ†Ø¬Ø§Ø±Ùˆ", "mounjaro",
    "Ø±ÙˆÙƒØªØ§Ù†", "roaccutane", "accutane", "isotretinoin",
    "Ø²ÙˆØ§Ø¬", "marriage", "premarital",
    "Ø¬Ù‡Ø§Ø¶", "Ø¥Ø¬Ù‡Ø§Ø¶", "miscarriage",
    "Ø±ÙŠØ§Ø¶ÙŠÙŠÙ†", "Ø±ÙŠØ§Ø¶ÙŠ", "athlete", "athletes",
    "dna", "well", "silver", "gold", "platinum", "nifty", "gender", "Ø¬ÙŠÙ†ÙŠ", "ÙˆØ±Ø§Ø«ÙŠ",
    "Ù…Ø¹Ø§Ø¯Ù†", "Ø§Ù…Ù„Ø§Ø­", "magnesium", "zinc", "calcium", "minerals",
    "Ø¯Ù‡ÙˆÙ†", "cholesterol", "lipid", "lipids",
}

_SYNONYMS: dict[str, tuple[str, ...]] = {
    "ØºØ¯Ù‡": ("ØºØ¯Ù‡", "Ø§Ù„ØºØ¯Ù‡", "ØºØ¯Ø¯", "Ø¯Ø±Ù‚ÙŠÙ‡", "Ø¯Ø±Ù‚ÙŠØ©", "thyroid", "thyroids", "tsh", "t3", "t4"),
    "Ø³ÙƒØ±ÙŠ": ("Ø³ÙƒØ±ÙŠ", "Ø³ÙƒØ±", "glucose", "diabetes", "diabetic", "hba1c", "Ø§Ù†Ø³ÙˆÙ„ÙŠÙ†", "insulin", "homa", "homa-ir"),
    "Ø´Ø¹Ø±": ("Ø´Ø¹Ø±", "hair", "ØªØ³Ø§Ù‚Ø·", "ØªÙ‚ØµÙ", "alopecia"),
    "ÙÙŠØªØ§Ù…ÙŠÙ†": ("ÙÙŠØªØ§Ù…ÙŠÙ†", "ÙÙŠØªØ§Ù…ÙŠÙ†Ø§Øª", "vitamin", "vitamins", "vit d", "vitamin d", "b12"),
    "Ø­Ø¯ÙŠØ¯": ("Ø­Ø¯ÙŠØ¯", "ÙØ±ÙŠØªÙŠÙ†", "Ù…Ø®Ø²ÙˆÙ†", "iron", "ferritin", "anaemia", "anemia", "ÙÙ‚Ø±", "Ø¯Ù…"),
    "Ù‡Ø±Ù…ÙˆÙ†": ("Ù‡Ø±Ù…ÙˆÙ†", "Ù‡Ø±Ù…ÙˆÙ†Ø§Øª", "hormone", "hormonal", "testosterone", "estrogen", "prolactin", "lh", "fsh"),
    "Ø§Ø·ÙØ§Ù„": ("Ø§Ø·ÙØ§Ù„", "Ø·ÙÙ„", "Ø£Ø·ÙØ§Ù„", "child", "children", "kids", "pediatric"),
    "Ø±Ø¬Ø§Ù„": ("Ø±Ø¬Ø§Ù„", "Ù„Ù„Ø±Ø¬Ø§Ù„", "men", "male", "man"),
    "Ù†Ø³Ø§Ø¡": ("Ù†Ø³Ø§Ø¡", "Ù„Ù„Ù†Ø³Ø§Ø¡", "Ù…Ø±Ø§Ù‡", "Ù…Ø±Ø£Ø©", "Ø§Ù…Ø±Ø£Ø©", "women", "woman", "female"),
    "Ø±Ù…Ø¶Ø§Ù†": ("Ø±Ù…Ø¶Ø§Ù†", "ramadan", "ØµÙŠØ§Ù…", "ØµØ§Ø¦Ù…"),
    "Ø§ÙƒØªØ¦Ø§Ø¨": ("Ø§ÙƒØªØ¦Ø§Ø¨", "depression", "mood", "Ù…Ø²Ø§Ø¬"),
    "ØµØ¯Ø§Ø¹": ("ØµØ¯Ø§Ø¹", "headache", "migraine"),
    "Ø¹Ø¸Ø§Ù…": ("Ø¹Ø¸Ø§Ù…", "bone", "bones", "calcium", "ÙÙŠØªØ§Ù…ÙŠÙ† Ø¯"),
    "ÙƒØ¨Ø¯": ("ÙƒØ¨Ø¯", "Ø§Ù„ÙƒØ¨Ø¯", "liver", "alt", "ast", "ggt", "alp"),
    "ÙƒÙ„Ù‰": ("ÙƒÙ„Ù‰", "Ø§Ù„ÙƒÙ„Ù‰", "ÙƒÙ„ÙŠÙ‡", "kidney", "renal", "creatinine", "egfr", "bun"),
    "Ø­Ø³Ø§Ø³ÙŠÙ‡": ("Ø­Ø³Ø§Ø³ÙŠÙ‡", "Ø­Ø³Ø§Ø³ÙŠØ©", "allergy", "allergies", "gluten", "Ù‚Ù…Ø­"),
    "Ø§ÙˆØ±Ø§Ù…": ("Ø§ÙˆØ±Ø§Ù…", "Ø§ÙˆØ±Ø§Ù…", "Ø³Ø±Ø·Ø§Ù†", "tumor", "tumour", "cancer", "marker"),
    "Ù…Ø¹Ø¯ÙŠÙ‡": ("Ù…Ø¹Ø¯ÙŠÙ‡", "Ù…Ø¹Ø¯ÙŠØ©", "infection", "infectious", "pcr", "std", "urine"),
    "Ù‚ÙˆÙ„ÙˆÙ†": ("Ù‚ÙˆÙ„ÙˆÙ†", "Ù‡Ø¶Ù…ÙŠ", "digestive", "gastro", "gluten", "Ø³ÙŠØ¨Ùˆ", "sibo"),
    "ØªÙƒÙ…ÙŠÙ…": ("ØªÙƒÙ…ÙŠÙ…", "sleeve", "bariatric", "weight"),
    "Ù…ÙˆÙ†Ø¬Ø§Ø±Ùˆ": ("Ù…ÙˆÙ†Ø¬Ø§Ø±Ùˆ", "mounjaro", "tirzepatide"),
    "Ø±ÙˆÙƒØªØ§Ù†": ("Ø±ÙˆÙƒØªØ§Ù†", "roaccutane", "accutane", "isotretinoin"),
    "Ø²ÙˆØ§Ø¬": ("Ø²ÙˆØ§Ø¬", "marriage", "premarital"),
    "Ø¬ÙŠÙ†ÙŠ": ("Ø¬ÙŠÙ†ÙŠ", "ÙˆØ±Ø§Ø«ÙŠ", "dna", "genetic", "genetics", "nifty", "well", "gender"),
}


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _base_norm(value: Any) -> str:
    text = normalize_arabic(_safe_str(value))
    if not text:
        return ""
    text = (
        text.replace("Ø©", "Ù‡")
        .replace("Ù‰", "ÙŠ")
        .replace("Ø£", "Ø§")
        .replace("Ø¥", "Ø§")
        .replace("Ø¢", "Ø§")
        .replace("Ø¤", "Ùˆ")
        .replace("Ø¦", "ÙŠ")
        .replace("Ú¾", "Ù‡")
        .replace("Ù€", "")
    )
    text = re.sub(r"[\u064B-\u065F\u0670]", "", text)
    text = re.sub(r"[^0-9a-zA-Z\u0600-\u06FF\s]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def _norm(value: Any) -> str:
    return _base_norm(value)


def _light_stem(token: str) -> str:
    token = _base_norm(token)
    if not token:
        return ""
    if token.startswith("Ø§Ù„") and len(token) > 3:
        token = token[2:]
    if token.startswith("Ù„Ù„") and len(token) > 3:
        token = token[2:]
    if token.endswith("ÙŠÙ‡") and len(token) > 4:
        token = token[:-2] + "ÙŠ"
    elif token.endswith("ÙŠÙ‡") and len(token) > 3:
        token = token[:-1]
    elif token.endswith("Ù‡") and len(token) > 3:
        token = token[:-1]
    elif token.endswith("Ø§Øª") and len(token) > 4:
        token = token[:-2]
    elif token.endswith("ÙˆÙ†") and len(token) > 4:
        token = token[:-2]
    elif token.endswith("ÙŠÙ†") and len(token) > 4:
        token = token[:-2]
    return token.strip()


def _english_alias_norms() -> dict[str, set[str]]:
    alias_map: dict[str, set[str]] = {}
    for canonical, values in _SYNONYMS.items():
        bag = {_base_norm(canonical), _light_stem(canonical)}
        for value in values:
            bag.add(_base_norm(value))
            bag.add(_light_stem(value))
        alias_map[_base_norm(canonical)] = {v for v in bag if v}
    return alias_map


_ALIAS_MAP = _english_alias_norms()


def _tokenize(value: Any) -> list[str]:
    text = _base_norm(value)
    if not text:
        return []
    raw_tokens = text.split()
    tokens: list[str] = []
    for token in raw_tokens:
        if not token or token in _STOPWORDS:
            continue
        if len(token) == 1:
            continue
        tokens.append(token)
    return tokens


def _expand_tokens(tokens: list[str]) -> set[str]:
    expanded: set[str] = set()
    for token in tokens:
        norm = _base_norm(token)
        stem = _light_stem(token)
        if norm:
            expanded.add(norm)
        if stem:
            expanded.add(stem)
        for variants in _ALIAS_MAP.values():
            if norm in variants or stem in variants:
                expanded.update(variants)
    return expanded


def _expand_synonyms(tokens: list[str]) -> set[str]:
    return _expand_tokens(tokens)


def _extract_bigrams(tokens: list[str]) -> set[str]:
    if len(tokens) < 2:
        return set()
    return {f"{tokens[i]} {tokens[i + 1]}" for i in range(len(tokens) - 1)}


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


def _query_without_price_words(query: str) -> str:
    text = _base_norm(query)
    if not text:
        return ""
    removal_phrases = (
        "ÙƒÙ… Ø³Ø¹Ø±", "ÙƒÙ… Ø§Ø³Ø¹Ø§Ø±", "Ù…Ø§ Ø³Ø¹Ø±", "ÙˆØ´ Ø³Ø¹Ø±", "Ø§ÙŠØ´ Ø³Ø¹Ø±", "Ø¨ÙƒÙ…", "price", "cost",
        "ÙˆØ´ ØªØ´Ù…Ù„", "Ø§ÙŠØ´ ØªØ´Ù…Ù„", "ÙˆØ´ ÙÙŠÙ‡Ø§", "Ø§ÙŠØ´ ÙÙŠÙ‡Ø§", "ØªÙØ§ØµÙŠÙ„",
    )
    for phrase in removal_phrases:
        text = text.replace(_base_norm(phrase), " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _record_text_blob(item: dict[str, Any]) -> str:
    return " | ".join(
        part for part in (
            _safe_str(item.get("package_name")),
            _safe_str(item.get("main_category")),
            _safe_str(item.get("offering_type")),
            _safe_str(item.get("description_short")),
            _safe_str(item.get("description_full")),
        )
        if part
    )


def _doc_frequency(records: list[dict[str, Any]]) -> dict[str, int]:
    df: dict[str, int] = {}
    for row in records:
        seen = set(_tokenize(_record_text_blob(row)))
        for token in seen:
            df[token] = df.get(token, 0) + 1
            stem = _light_stem(token)
            if stem:
                df[stem] = df.get(stem, 0) + 1
    return df


@lru_cache(maxsize=1)
def load_packages_records() -> list[dict[str, Any]]:
    """Load runtime package records from packages_clean.jsonl only."""
    if not PACKAGES_JSONL_PATH.exists():
        return []

    base_rows: list[dict[str, Any]] = []
    with PACKAGES_JSONL_PATH.open("r", encoding="utf-8") as f:
        for raw_line in f:
            line = _safe_str(raw_line)
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue

            package_name = _safe_str(obj.get("package_name"))
            main_category = _safe_str(obj.get("main_category"))
            offering_type = _safe_str(obj.get("offering_type"))
            if not package_name or not main_category or not offering_type:
                continue

            item = dict(obj)
            item["id"] = _safe_str(obj.get("id"))
            item["source"] = _safe_str(obj.get("source")) or "packages"
            item["main_category"] = main_category
            item["offering_type"] = offering_type
            item["package_name"] = package_name
            item["description_short"] = _safe_str(obj.get("description_short"))
            item["description_full"] = _safe_str(obj.get("description_full"))
            item["price_raw"] = _safe_str(obj.get("price_raw"))
            item["price_number"] = _to_float_or_none(obj.get("price_number"))
            item["currency"] = _safe_str(obj.get("currency"))
            item["included_count"] = obj.get("included_count")
            item["runtime_present"] = bool(obj.get("runtime_present"))
            item["review_issues"] = _safe_str(obj.get("review_issues"))
            item["source_row"] = obj.get("source_row")
            item["is_active"] = bool(obj.get("is_active", True))
            base_rows.append(item)

    # Deduplicate exact repeated entries by normalized name + category + price + offering_type
    deduped: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str, str, str]] = set()
    for item in base_rows:
        key = (
            _base_norm(item.get("package_name")),
            _base_norm(item.get("main_category")),
            _safe_str(item.get("offering_type")),
            _safe_str(item.get("price_raw")) or str(item.get("price_number") or ""),
        )
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(item)

    df = _doc_frequency(deduped)

    rows: list[dict[str, Any]] = []
    for item in deduped:
        text_blob = _record_text_blob(item)
        package_name_norm = _base_norm(item.get("package_name"))
        main_category_norm = _base_norm(item.get("main_category"))
        package_name_tokens = _tokenize(item.get("package_name"))
        category_tokens = _tokenize(item.get("main_category"))
        desc_tokens = _tokenize(" ".join([
            _safe_str(item.get("description_short")),
            _safe_str(item.get("description_full"))[:1200],
        ]))
        blob_tokens = _tokenize(text_blob)

        all_tokens = list(dict.fromkeys(package_name_tokens + category_tokens + desc_tokens + blob_tokens))
        all_stems = {_light_stem(t) for t in all_tokens if _light_stem(t)}
        bigrams = _extract_bigrams(package_name_tokens)
        keyword_weights: dict[str, float] = {}
        for token in all_tokens:
            stem = _light_stem(token)
            doc_count = max(1, df.get(token) or df.get(stem) or 1)
            rarity_bonus = 1.0 / math.sqrt(doc_count)
            base = 1.2 if token in package_name_tokens else 0.7
            if token in _STRONG_KEYWORDS or stem in _STRONG_KEYWORDS:
                base += 1.3
            if token in _GENERIC_LOW_SIGNAL or stem in _GENERIC_LOW_SIGNAL:
                base -= 0.5
            keyword_weights[token] = round(max(0.15, base + rarity_bonus), 4)

        row = dict(item)
        row["package_name_norm"] = package_name_norm
        row["main_category_norm"] = main_category_norm
        row["text_blob_norm"] = _base_norm(text_blob)
        row["package_name_tokens"] = package_name_tokens
        row["category_tokens"] = category_tokens
        row["desc_tokens"] = desc_tokens
        row["all_tokens"] = all_tokens
        row["all_stems"] = list(all_stems)
        row["name_bigrams"] = list(bigrams)
        row["keyword_weights"] = keyword_weights
        rows.append(row)

    return rows


def _is_price_query(query_norm: str) -> bool:
    return any(_norm(h) in query_norm for h in _PRICE_HINTS)


def _is_general_query(query_norm: str) -> bool:
    return any(_norm(h) in query_norm for h in _GENERAL_HINTS)


def _is_general_listing_query(query_norm: str) -> bool:
    return any(_norm(h) in query_norm for h in _GENERAL_LISTING_HINTS)


def _is_detail_query(query_norm: str) -> bool:
    return any(_norm(h) in query_norm for h in _DETAIL_HINTS)


def _detect_category(query_norm: str, records: list[dict[str, Any]]) -> str:
    categories = {
        _safe_str(r.get("main_category")): _safe_str(r.get("main_category_norm")) for r in records
    }
    for cat, cat_norm in categories.items():
        if cat_norm and cat_norm in query_norm:
            return cat

    for category, hints in _CATEGORY_HINTS.items():
        if any(_norm(h) in query_norm for h in hints):
            return category
    return ""


def _is_category_like_query(query_norm: str, detected_category: str) -> bool:
    if not query_norm:
        return False
    if detected_category and detected_category and _base_norm(detected_category) in query_norm:
        return True

    category_tokens = (
        "Ø§Ù„ØªØ­Ø§Ù„ÙŠÙ„ Ø§Ù„Ø°Ø§ØªÙŠÙ‡",
        "Ø§Ù„ØªØ­Ø§Ù„ÙŠÙ„ Ø§Ù„Ø°Ø§ØªÙŠØ©",
        "Ø§Ù„ØªØ­Ø§Ù„ÙŠÙ„ Ø§Ù„Ø¬ÙŠÙ†ÙŠÙ‡",
        "Ø§Ù„ØªØ­Ø§Ù„ÙŠÙ„ Ø§Ù„Ø¬ÙŠÙ†ÙŠØ©",
        "Ø§Ù„Ø¨Ø§Ù‚Ø§Øª Ø§Ù„Ø¬ÙŠÙ†ÙŠÙ‡",
        "Ø§Ù„Ø¨Ø§Ù‚Ø§Øª Ø§Ù„Ø¬ÙŠÙ†ÙŠØ©",
        "ÙØ¦Ù‡",
        "ÙØ¦Ø©",
        "ØªØµÙ†ÙŠÙ",
        "category",
    )
    return any(_norm(t) in query_norm for t in category_tokens)


def _score_package_match(query: str, record: dict[str, Any]) -> float:
    query_tokens = _tokenize(query)

    combined_text = " ".join([
        str(record.get("package_name", "") or ""),
        str(record.get("description", "") or ""),
        str(record.get("full_description", "") or ""),
        str(record.get("category", "") or ""),
    ])

    record_tokens = _tokenize(combined_text)

    if not record_tokens:
        return 0

    query_set = _expand_synonyms(query_tokens)
    record_set = _expand_synonyms(record_tokens)

    score = 0

    # Exact matches
    for t in query_set:
        if t in record_set:
            score += 4

    # Partial matches
    for qt in query_set:
        for rt in record_set:
            if qt in rt or rt in qt:
                score += 2

    # Strong keyword boost
    for key in _SYNONYMS:
        if key in query_set and key in record_set:
            score += 6

    # Multi-token bonus
    if len(query_set.intersection(record_set)) >= 2:
        score += 3

    # Penalty
    if score == 0:
        score -= 2

    return score
def _find_specific_package(query_text: str, records: list[dict[str, Any]]) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_score = float("-inf")
    second_score = float("-inf")

    for record in records:
        score = _score_package_match(query_text, record)
        if score > best_score:
            second_score = best_score
            best_score = score
            best = record
        elif score > second_score:
            second_score = score

    if best is None:
        return None

    # Conservative threshold + margin to reduce wrong selections.
    if best_score < 8.0:
        return None
    if second_score > float("-inf") and best_score - second_score < 1.5 and best_score < 18.0:
        return None
    return best


def _format_general_overview(records: list[dict[str, Any]], conversation_id: UUID | None = None) -> str:
    active_rows = [r for r in records if "package" in _safe_str(r.get("offering_type")).lower()]
    rows = active_rows or records
    rows = sorted(
        rows,
        key=lambda r: (
            0 if isinstance(r.get("price_number"), (int, float)) else 1,
            _safe_str(r.get("package_name")),
        ),
    )
    top_rows = rows[:20]

    if conversation_id is not None and top_rows:
        save_selection_state(
            conversation_id,
            options=[
                {
                    "id": _safe_str(row.get("id")) or f"package_option::{idx}",
                    "label": _safe_str(row.get("package_name")),
                    "selection_payload": {"package_name": _safe_str(row.get("package_name"))},
                }
                for idx, row in enumerate(top_rows, start=1)
            ],
            selection_type="package",
            query_type="package_general",
        )

    counts: dict[str, int] = {}
    for r in rows:
        cat = _safe_str(r.get("main_category"))
        if cat:
            counts[cat] = counts.get(cat, 0) + 1

    lines = ["Ø§Ù„Ø¨Ø§Ù‚Ø§Øª Ø§Ù„Ù…ØªØ§Ø­Ø© Ø­Ø§Ù„ÙŠÙ‹Ø§:"]
    for idx, row in enumerate(top_rows, start=1):
        name = _safe_str(row.get("package_name"))
        price = row.get("price_number")
        if isinstance(price, (int, float)):
            lines.append(f"{idx}) {name} - {price:g} {_safe_str(row.get('currency') or 'Ø±ÙŠØ§Ù„')}")
        else:
            lines.append(f"{idx}) {name}")
    if len(rows) > len(top_rows):
        lines.append(f"... ÙŠÙˆØ¬Ø¯ Ø£ÙŠØ¶Ù‹Ø§ {len(rows) - len(top_rows)} Ø¨Ø§Ù‚Ø§Øª Ø¥Ø¶Ø§ÙÙŠØ©.")
    lines.append("Ø§ÙƒØªØ¨ Ø§Ø³Ù… Ø§Ù„Ø¨Ø§Ù‚Ø© Ù…Ø¨Ø§Ø´Ø±Ø© Ø£Ùˆ Ø±Ù‚Ù…Ù‡Ø§ Ø£Ùˆ Ø§Ù„ÙƒÙ„Ù…Ø§Øª Ø§Ù„Ø£Ù‚Ø±Ø¨ Ù„Ù‡Ø§ Ø¹Ø´Ø§Ù† Ø£Ø¹Ø±Ø¶ Ø§Ù„ØªÙØ§ØµÙŠÙ„.")
    return "\n".join(lines)


def _format_category_packages(category: str, records: list[dict[str, Any]], conversation_id: UUID | None = None) -> str:
    rows = [r for r in records if _safe_str(r.get("main_category")) == category]
    if not rows:
        return "Ù…Ø§ Ù„Ù‚ÙŠØª Ø¨Ø§Ù‚Ø§Øª ÙÙŠ Ù‡Ø°Ù‡ Ø§Ù„ÙØ¦Ø© Ø­Ø§Ù„ÙŠÙ‹Ø§."

    if conversation_id is not None:
        save_selection_state(
            conversation_id,
            options=[
                {
                    "id": _safe_str(row.get("id")) or f"package_option::{idx}",
                    "label": _safe_str(row.get("package_name")),
                    "selection_payload": {"package_name": _safe_str(row.get("package_name"))},
                }
                for idx, row in enumerate(rows[:20], start=1)
            ],
            selection_type="package",
            query_type="package_category",
        )

    lines = [f"Ø§Ù„Ø¨Ø§Ù‚Ø§Øª Ø§Ù„Ù…ØªØ§Ø­Ø© Ø¶Ù…Ù† ÙØ¦Ø© {category}:"]
    for idx, r in enumerate(rows[:20], start=1):
        name = _safe_str(r.get("package_name"))
        price = r.get("price_number")
        if isinstance(price, (int, float)):
            lines.append(f"{idx}) {name} - {price:g} {_safe_str(r.get('currency') or 'Ø±ÙŠØ§Ù„')}")
        else:
            lines.append(f"{idx}) {name}")
    if len(rows) > 20:
        lines.append(f"... ({len(rows) - 20} Ø¹Ù†Ø§ØµØ± Ø¥Ø¶Ø§ÙÙŠØ©)")
    lines.append("Ø§ÙƒØªØ¨ Ø§Ø³Ù… Ø§Ù„Ø¹Ù†ØµØ± Ø£Ùˆ Ø±Ù‚Ù…Ù‡ Ø¹Ø´Ø§Ù† Ø£Ø¹Ø±Ø¶ ØªÙØ§ØµÙŠÙ„Ù‡.")
    return "\n".join(lines)


def _format_package_details(record: dict[str, Any]) -> str:
    name = _safe_str(record.get("package_name"))
    category = _safe_str(record.get("main_category"))
    offering_type = _safe_str(record.get("offering_type"))
    desc = _safe_str(record.get("description_short")) or _safe_str(record.get("description_full"))
    currency = _safe_str(record.get("currency") or "Ø±ÙŠØ§Ù„")
    price = record.get("price_number")

    lines = [
        f"{name}",
        f"Ø§Ù„ÙØ¦Ø©: {category}",
        f"Ø§Ù„Ù†ÙˆØ¹: {offering_type}",
    ]
    if desc:
        lines.append(f"Ø§Ù„ÙˆØµÙ: {desc}")
    if isinstance(price, (int, float)):
        lines.append(f"Ø§Ù„Ø³Ø¹Ø±: {price:g} {currency}")
    else:
        lines.append(_PRICE_NOT_AVAILABLE)
    return "\n".join(lines)


def _format_package_price(record: dict[str, Any]) -> str:
    name = _safe_str(record.get("package_name"))
    currency = _safe_str(record.get("currency") or "Ø±ÙŠØ§Ù„")
    price = record.get("price_number")
    if isinstance(price, (int, float)):
        return f"Ø³Ø¹Ø± {name}: {price:g} {currency}."
    return _PRICE_NOT_AVAILABLE


def resolve_packages_query(user_text: str, conversation_id: UUID | None = None) -> dict[str, Any]:
    """Resolve package-like queries deterministically from packages_clean.jsonl."""
    query = _safe_str(user_text)
    query_norm = _norm(query)
    if not query_norm:
        return {
            "matched": False,
            "answer": "",
            "route": "packages_no_match",
            "meta": {"query_type": "no_match", "reason": "empty_query"},
        }

    records = [r for r in load_packages_records() if bool(r.get("is_active", True))]
    if not records:
        records = load_packages_records()
    if not records:
        return {
            "matched": False,
            "answer": "",
            "route": "packages_no_match",
            "meta": {"query_type": "no_match", "reason": "packages_data_unavailable"},
        }

    category = _detect_category(query_norm, records)
    category_like = _is_category_like_query(query_norm, category)
    general_like = _is_general_query(query_norm)
    general_listing_like = _is_general_listing_query(query_norm)
    price_query = _is_price_query(query_norm)
    detail_query = _is_detail_query(query_norm)
    specific_match = _find_specific_package(query, records)

    # Category queries should win when they are clearly asking about a category list,
    # unless we have a strong specific package match.
    if category and category_like and not price_query and specific_match is None:
        return {
            "matched": True,
            "answer": _format_category_packages(category, records, conversation_id),
            "route": "packages_category",
            "meta": {
                "query_type": "package_category",
                "category": category,
            },
        }

    # Explicit package-listing requests should return the general overview
    # before specific package matching.
    if general_listing_like and not price_query and not category:
        return {
            "matched": True,
            "answer": _format_general_overview(records, conversation_id),
            "route": "packages_general",
            "meta": {
                "query_type": "package_general",
                "categories_count": len({_safe_str(r.get('main_category')) for r in records}),
            },
        }

    if specific_match is not None and price_query:
        package_id = _safe_str(specific_match.get("id"))
        return {
            "matched": True,
            "answer": _format_package_price(specific_match),
            "route": "packages_price",
            "meta": {
                "query_type": "package_price_query",
                "matched_package_id": package_id,
                "matched_package_name": _safe_str(specific_match.get("package_name")),
                "category": _safe_str(specific_match.get("main_category")),
                "price_available": isinstance(specific_match.get("price_number"), (int, float)),
            },
        }

    if specific_match is not None:
        package_id = _safe_str(specific_match.get("id"))
        route = "packages_specific_details" if detail_query else "packages_specific"
        return {
            "matched": True,
            "answer": _format_package_details(specific_match),
            "route": route,
            "meta": {
                "query_type": "package_specific",
                "matched_package_id": package_id,
                "matched_package_name": _safe_str(specific_match.get("package_name")),
                "category": _safe_str(specific_match.get("main_category")),
            },
        }

    if category:
        return {
            "matched": True,
            "answer": _format_category_packages(category, records, conversation_id),
            "route": "packages_category",
            "meta": {
                "query_type": "package_category",
                "category": category,
            },
        }

    if general_like or "Ø¨Ø§Ù‚Ù‡" in query_norm or "Ø¨Ø§Ù‚Ø§Øª" in query_norm or "package" in query_norm:
        return {
            "matched": True,
            "answer": _format_general_overview(records, conversation_id),
            "route": "packages_general",
            "meta": {
                "query_type": "package_general",
                "categories_count": len({_safe_str(r.get('main_category')) for r in records}),
            },
        }

    if price_query:
        return {
            "matched": True,
            "answer": _PACKAGE_NOT_FOUND,
            "route": "packages_price",
            "meta": {
                "query_type": "package_price_query",
                "matched_package_id": "",
                "reason": "price_query_without_specific_package",
            },
        }

    return {
        "matched": False,
        "answer": "",
        "route": "packages_no_match",
        "meta": {"query_type": "no_match", "reason": "not_packages_intent"},
    }


if __name__ == "__main__":
    try:
        import sys

        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    samples = [
        "ÙˆØ´ Ø¹Ù†Ø¯ÙƒÙ… Ø¨Ø§Ù‚Ø§Øª",
        "Ø¨Ø§Ù‚Ø§Øª Ø±Ù…Ø¶Ø§Ù†",
        "Ø¨Ø§Ù‚Ø© Ù†Ù‡Ø§Ø± Ø±Ù…Ø¶Ø§Ù† Ø§Ù„Ø´Ø§Ù…Ù„Ø©",
        "ÙƒÙ… Ø³Ø¹Ø± Ø¨Ø§Ù‚Ø© Ù†Ù‡Ø§Ø± Ø±Ù…Ø¶Ø§Ù† Ø§Ù„Ø´Ø§Ù…Ù„Ø©",
        "Ø¨ÙƒÙ… Ø¨Ø§Ù‚Ù‡ ØµØ­Ù‡ Ø§Ù„ØºØ¯Ù‡",
        "thyroid package",
        "Ø§Ø¨ÙŠ Ø´ÙŠØ¡ Ù„Ù„Ø´Ø¹Ø±",
    ]
    for text in samples:
        result = resolve_packages_query(text)
        print(f"INPUT: {text}")
        print(f"ROUTE: {result.get('route')}")
        print(f"MATCHED: {result.get('matched')}")
        print(f"META: {result.get('meta')}")
        print(f"ANSWER: {result.get('answer')}")
        print("-" * 72)

