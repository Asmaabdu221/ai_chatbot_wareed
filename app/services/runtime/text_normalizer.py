"""Robust Arabic text normalization helpers for FAQ matching and retrieval."""

from __future__ import annotations

import re
from typing import Any


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Arabic diacritics / tashkeel
_ARABIC_DIACRITICS_RE = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]")

# Keep only:
# - Arabic letters
# - English letters
# - digits
# - whitespace
# Arabic letters:
#   \u0621-\u063A and \u0641-\u064A
# Digits:
#   0-9
#   Arabic-Indic digits: \u0660-\u0669
#   Eastern Arabic-Indic digits: \u06F0-\u06F9
_NOISE_RE = re.compile(
    r"[^A-Za-z0-9\u0660-\u0669\u06F0-\u06F9\u0621-\u063A\u0641-\u064A\s]"
)

_MULTISPACE_RE = re.compile(r"\s+")
_TATWEEL = "ـ"


# ---------------------------------------------------------------------------
# Character normalization
# ---------------------------------------------------------------------------

_CHAR_NORMALIZATION = str.maketrans(
    {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ى": "ي",
        "ة": "ه",
        "ؤ": "و",
        "ئ": "ي",
    }
)

# Arabic-Indic digits -> Latin digits
_DIGIT_MAP = str.maketrans(
    "٠١٢٣٤٥٦٧٨٩",
    "0123456789",
)

# Eastern Arabic-Indic digits -> Latin digits
_DIGIT_MAP_EXTENDED = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹",
    "0123456789",
)


# ---------------------------------------------------------------------------
# Common colloquial replacements
# IMPORTANT: keep longest phrases first
# ---------------------------------------------------------------------------

_COLLOQUIAL_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("وشو", "ما"),
    ("وش", "ما"),
    ("ايش", "ما"),
    ("اش", "ما"),
    ("شنو", "ما"),
    ("فين", "اين"),
    ("وين", "اين"),
    ("الحين", "حاليا"),
    ("دحين", "حاليا"),
    ("هسه", "حاليا"),
    ("لسه", "مازال"),
    ("لسى", "مازال"),
    ("النتايج", "النتائج"),
    ("النتيجه", "النتائج"),
    ("نتيجتي", "النتائج"),
    ("تحاليلي", "التحاليل"),
    ("تحاليلك", "التحاليل"),
    ("في البيت", "المنزل"),
    ("للبيت", "المنزل"),
    ("سحب منزلي", "الزيارات المنزلية"),
    ("زيارة منزلية", "الزيارات المنزلية"),
    ("شبكة", "بطاقه"),
    ("بطاقة", "بطاقه"),
)


# ---------------------------------------------------------------------------
# Stopwords
# Keep light and conservative
# ---------------------------------------------------------------------------

_STOPWORDS = {
    "من",
    "في",
    "على",
    "الى",
    "عن",
    "و",
    "او",
    "يا",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _safe_str(value: Any) -> str:
    """Convert any value to a stripped string safely."""
    return str(value or "").strip()


def normalize_arabic(text: str) -> str:
    """
    Normalize Arabic/Latin text into a deterministic matching-friendly form.

    Steps:
    - lowercase English text
    - remove Arabic diacritics
    - remove tatweel
    - normalize common Arabic character variants
    - normalize digits
    - remove punctuation / noisy symbols
    - apply light colloquial replacements
    - collapse repeated whitespace
    """
    value = _safe_str(text)
    if not value:
        return ""

    value = value.lower()

    # Remove Arabic diacritics
    value = _ARABIC_DIACRITICS_RE.sub("", value)

    # Remove tatweel
    value = value.replace(_TATWEEL, "")

    # Normalize characters
    value = value.translate(_CHAR_NORMALIZATION)

    # Normalize digits
    value = value.translate(_DIGIT_MAP)
    value = value.translate(_DIGIT_MAP_EXTENDED)

    # Remove punctuation / noise
    value = _NOISE_RE.sub(" ", value)

    # Apply light colloquial replacements
    for old, new in _COLLOQUIAL_REPLACEMENTS:
        old_n = _safe_str(old)
        new_n = _safe_str(new)
        if old_n and old_n in value:
            value = value.replace(old_n, new_n)

    # Collapse whitespace
    value = _MULTISPACE_RE.sub(" ", value).strip()

    return value


def tokenize_arabic(text: str, remove_stopwords: bool = True) -> list[str]:
    """
    Normalize text then split into tokens.

    Args:
        text: input text
        remove_stopwords: whether to remove light Arabic stopwords

    Returns:
        list of non-empty tokens
    """
    normalized = normalize_arabic(text)
    if not normalized:
        return []

    tokens = [token for token in normalized.split(" ") if token]

    if remove_stopwords:
        tokens = [token for token in tokens if token not in _STOPWORDS]

    return tokens


def token_set(text: str, remove_stopwords: bool = True) -> set[str]:
    """Return a set of normalized tokens."""
    return set(tokenize_arabic(text, remove_stopwords=remove_stopwords))


if __name__ == "__main__":
    samples = [
        "هل تحليل السكر التراكمي يحتاج صيام؟",
        "أين تتواجد فروع مختبرات وريد؟",
        "هل يتم إرسال النتائج إلكترونيًا؟",
        "وش الخدمات اللي عندكم",
        "متى تطلع نتيجتي",
        "هل احد يقدر يشوف نتيجتي",
        "فيه عروض الحين",
        "وين اقرب فرع بالرياض",
        "وشو طرق الدفع؟",
        "١٢٣ / ۱۲۳ / 123",
    ]

    for s in samples:
        print(f"INPUT : {s}")
        print(f"NORM  : {normalize_arabic(s)}")
        print(f"TOKENS: {tokenize_arabic(s)}")
        print("-" * 50)
