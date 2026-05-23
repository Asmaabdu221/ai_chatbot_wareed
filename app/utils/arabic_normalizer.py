"""
Arabic text normalization utility (self-contained).

Used by the Lab RAG v2 pipeline for matching user queries against the
synonym index and test names. Deterministic, dependency-free.

Public API:
    normalize(text) -> str
    normalize_list(terms) -> list[str]

Backward-compatible shims `normalize_arabic` / `normalize_for_matching`
are kept so any existing dynamic importers keep working.
"""

from __future__ import annotations

import re

# Tashkeel (diacritics) + superscript alef, and tatweel.
_TASHKEEL = re.compile(r"[ً-ْٰـ]")
# Allowed characters after normalization: Arabic block, latin a-z, digits,
# spaces, and the medical symbols / - %.
_ALLOWED = re.compile(r"[^a-z0-9؀-ۿ/\-% ]+")
_MULTISPACE = re.compile(r"\s+")

_ALEF_VARIANTS = {
    "أ": "ا",  # hamza-on-alef -> alef
    "إ": "ا",  # hamza-under-alef -> alef
    "آ": "ا",  # madda-on-alef -> alef
    "ٱ": "ا",  # wasla-alef -> alef
}


def normalize(text: str) -> str:
    """Normalize Arabic/mixed text for robust matching.

    Steps: strip diacritics & tatweel, unify alef variants -> alef,
    unify yaa (ya maqsura -> ya) and taa marbuta -> haa, lowercase latin
    text, drop punctuation except the medical symbols ``/ - %``, and
    collapse whitespace.
    """
    if not text or not isinstance(text, str):
        return ""
    s = text.strip()
    s = _TASHKEEL.sub("", s)
    for src, dst in _ALEF_VARIANTS.items():
        s = s.replace(src, dst)
    s = s.replace("ى", "ي")  # ya maqsura -> ya
    s = s.replace("ة", "ه")  # taa marbuta -> haa
    s = s.lower()
    s = _ALLOWED.sub(" ", s)
    s = _MULTISPACE.sub(" ", s).strip()
    return s


def normalize_list(terms: list[str]) -> list[str]:
    """Normalize each term (non-empty, de-duplicated, order-preserving)."""
    out: list[str] = []
    seen: set[str] = set()
    for t in terms or []:
        n = normalize(t)
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def normalize_arabic(text: str) -> str:
    """Deprecated alias for :func:`normalize`."""
    return normalize(text)


def normalize_for_matching(text: str) -> str:
    """Deprecated alias for :func:`normalize`."""
    return normalize(text)
