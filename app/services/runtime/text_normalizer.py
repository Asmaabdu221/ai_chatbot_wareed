"""Lightweight Arabic text normalization helpers for FAQ matching."""

from __future__ import annotations

import re


_ARABIC_DIACRITICS_RE = re.compile(r"[\u064B-\u065F\u0670]")
_PUNCT_NOISE_RE = re.compile(r"[^\u0600-\u06FFA-Za-z0-9\s]")
_MULTISPACE_RE = re.compile(r"\s+")


def normalize_arabic(text: str) -> str:
    """Normalize Arabic/Latin text into a deterministic, q_norm-like form."""
    value = str(text or "").strip()
    if not value:
        return ""

    value = value.lower()
    value = _ARABIC_DIACRITICS_RE.sub("", value)
    value = value.replace("ـ", "")
    value = (
        value.replace("أ", "ا")
        .replace("إ", "ا")
        .replace("آ", "ا")
        .replace("ى", "ي")
        .replace("ة", "ه")
    )
    value = _PUNCT_NOISE_RE.sub(" ", value)
    value = _MULTISPACE_RE.sub(" ", value).strip()
    return value


def tokenize_arabic(text: str) -> list[str]:
    """Normalize text then split into non-empty tokens."""
    normalized = normalize_arabic(text)
    if not normalized:
        return []
    return [tok for tok in normalized.split(" ") if tok]


if __name__ == "__main__":
    samples = [
        "هل تحليل السكر التراكمي يحتاج صيام؟",
        "أين تتواجد فروع مختبرات وريد؟",
        "هل يتم إرسال النتائج إلكترونيًا؟",
    ]
    for s in samples:
        print(f"IN : {s}")
        print(f"NORM: {normalize_arabic(s)}")
        print(f"TOKS: {tokenize_arabic(s)}")
        print("-" * 40)
