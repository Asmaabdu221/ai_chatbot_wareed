"""
Arabic Text Normalization Utility
=================================
تطبيع النص العربي للبحث والتطابق:
- إزالة التشكيل
- توحيد الألف (ا، أ، إ، آ → ا)
- توحيد الياء والألف المقصورة
- إزالة المدود
- Case-insensitive (للنص الإنجليزي)

Author: RAG System Update
Date: 2026-02-15
"""

import re
import unicodedata
from typing import Optional

# Arabic diacritics (tashkeel) - remove for normalization
ARABIC_DIACRITICS = re.compile(
    r'[\u064B-\u065F\u0670]'  # Fatha, Damma, Kasra, Shadda, Sukun, etc.
)

# Alef variants → unified alef
ALEF_PATTERN = re.compile(r'[أإآٱ]')
ALEF_REPLACEMENT = 'ا'

# Ya variants → unified ya
YA_PATTERN = re.compile(r'[ىي]')
YA_REPLACEMENT = 'ي'

# Alef Maksura → Ya
ALEF_MAKSURA_PATTERN = re.compile(r'ى')
ALEF_MAKSURA_REPLACEMENT = 'ي'

# Tatweel (kashida) - remove
TATWEEL = '\u0640'
TATWEEL_PATTERN = re.compile(TATWEEL)

# Hamza variants - normalize
HAMZA_PATTERNS = [
    (re.compile(r'[ؤئ]'), 'ء'),
]

# Optional: normalize some common variations
# e.g. هـ → ه
HEH_PATTERN = re.compile(r'ه\u200e')  # Heh + LRM


def remove_diacritics(text: str) -> str:
    """Remove Arabic diacritics (tashkeel) from text."""
    if not text:
        return ""
    return ARABIC_DIACRITICS.sub('', text)


def normalize_arabic(text: str) -> str:
    """
    Full Arabic normalization for matching and search.
    
    - Remove diacritics
    - Unify Alef (ا، أ، إ، آ → ا)
    - Unify Ya (ى، ي → ي)
    - Remove Tatweel (kashida)
    - Collapse multiple spaces
    - Strip
    """
    if not text or not isinstance(text, str):
        return ""
    
    t = text.strip()
    if not t:
        return ""
    
    # Remove diacritics
    t = remove_diacritics(t)
    
    # Unify Alef variants
    t = ALEF_PATTERN.sub(ALEF_REPLACEMENT, t)
    
    # Unify Alef Maksura and Ya
    t = ALEF_MAKSURA_PATTERN.sub(ALEF_MAKSURA_REPLACEMENT, t)
    
    # Remove Tatweel
    t = TATWEEL_PATTERN.sub('', t)
    
    # Collapse spaces
    t = re.sub(r'\s+', ' ', t)
    
    return t.strip()


def normalize_for_search(text: str) -> str:
    """
    Normalize text for search (query or document).
    Same as normalize_arabic but also lower for English parts.
    """
    t = normalize_arabic(text)
    return t.lower() if t else ""


def normalize_for_matching(text: str) -> str:
    """
    Normalize for fuzzy/Levenshtein matching.
    More aggressive: remove punctuation, extra spaces.
    """
    t = normalize_arabic(text)
    if not t:
        return ""
    # Remove common punctuation for matching
    t = re.sub(r'[^\w\s\u0600-\u06FF]', ' ', t)
    t = re.sub(r'\s+', ' ', t)
    return t.strip().lower()
