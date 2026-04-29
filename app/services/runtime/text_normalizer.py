"""Robust Arabic text normalization helpers for FAQ matching and retrieval."""

from __future__ import annotations

import re
from typing import Any
import warnings

from app.services.runtime.unified_normalizer import get_wareed_normalizer


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
_PUNCTUATION_RE = re.compile(r"[؟?,،\.;:!()\[\]{}\"'`“”«»…/\\|+\-_=~@#$%^&*<>]")
_AR_LETTER_NUM_JOIN_RE = re.compile(r"(?<![\w\u0621-\u064A])([\u0621-\u064A])\s+(\d+)(?![\w\u0621-\u064A])")
_EN_LETTER_NUM_JOIN_RE = re.compile(r"(?<!\w)([A-Za-z])\s+(\d+)(?!\w)")
_NUM_LETTER_JOIN_RE = re.compile(r"(?<!\w)(\d+)\s+([A-Za-z])(?!\w)")
_HBA1C_JOIN_RE = re.compile(r"\bhb\s*a1c\b", re.IGNORECASE)


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


def normalize_digits(text: str) -> str:
    """Normalize Arabic-Indic digits to Latin digits."""
    value = _safe_str(text)
    if not value:
        return ""
    value = value.translate(_DIGIT_MAP)
    value = value.translate(_DIGIT_MAP_EXTENDED)
    return value


def normalize_punctuation(text: str) -> str:
    """Replace punctuation/noise with spaces while keeping letters and digits."""
    value = _safe_str(text)
    if not value:
        return ""
    value = _PUNCTUATION_RE.sub(" ", value)
    value = _NOISE_RE.sub(" ", value)
    return _MULTISPACE_RE.sub(" ", value).strip()


def normalize_token_joining(text: str) -> str:
    """
    Join medically common split alpha-numeric tokens safely:
    - ب 12 -> ب12
    - B 12 -> b12
    - 12 B -> 12b
    - Hb A1c -> hba1c
    """
    value = _safe_str(text)
    if not value:
        return ""
    value = _HBA1C_JOIN_RE.sub("hba1c", value)
    value = _AR_LETTER_NUM_JOIN_RE.sub(r"\1\2", value)
    value = _EN_LETTER_NUM_JOIN_RE.sub(r"\1\2", value)
    value = _NUM_LETTER_JOIN_RE.sub(r"\1\2", value)
    return _MULTISPACE_RE.sub(" ", value).strip()


def normalize_text(text: str) -> str:
    """General normalized text pipeline for consistent matching/search."""
    value = _safe_str(text)
    if not value:
        return ""

    value = value.lower()
    value = _ARABIC_DIACRITICS_RE.sub("", value)
    value = value.replace(_TATWEEL, "")
    value = value.translate(_CHAR_NORMALIZATION)
    value = normalize_digits(value)
    value = normalize_punctuation(value)
    value = normalize_token_joining(value)
    return _MULTISPACE_RE.sub(" ", value).strip()


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
    warnings.warn(
        "normalize_arabic() is deprecated. Use WareedNormalizer.normalize() from unified_normalizer.",
        DeprecationWarning,
        stacklevel=2,
    )
    return get_wareed_normalizer().normalize(text)


def normalize_for_match(text: str) -> str:
    """
    Project-wide matcher normalization:
    - base Arabic/Latin cleanup
    - colloquial normalization (existing behavior)
    - safe alpha-numeric token joining
    """
    warnings.warn(
        "normalize_for_match() is deprecated. Use WareedNormalizer.normalize() from unified_normalizer.",
        DeprecationWarning,
        stacklevel=2,
    )
    value = get_wareed_normalizer().normalize(text)
    if not value:
        return ""
    return normalize_token_joining(value)


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
