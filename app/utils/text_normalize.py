"""
Shared text normalization helpers for Arabic-first routing and slot extraction.
"""

from __future__ import annotations

import re

_ARABIC_INDIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_EASTERN_ARABIC_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
_TASHKEEL_RE = re.compile(r"[\u064B-\u065F\u0670\u0640]")


def normalize_text(text: str | None) -> str:
    """
    Normalize Arabic text for deterministic routing/search.

    Rules:
    - remove tashkeel
    - أ/إ/آ -> ا
    - ى -> ي
    - ة -> ه
    - Arabic digits -> Latin digits
    - collapse spaces
    """
    value = (text or "").strip().lower()
    if not value:
        return ""

    value = _TASHKEEL_RE.sub("", value)
    value = value.translate(_ARABIC_INDIC_DIGITS).translate(_EASTERN_ARABIC_DIGITS)
    value = value.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    value = value.replace("ى", "ي").replace("ؤ", "و").replace("ئ", "ي").replace("ة", "ه")
    value = re.sub(r"\s+", " ", value)
    return value.strip()

