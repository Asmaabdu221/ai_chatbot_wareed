"""
Shared text normalization helpers for Arabic-first routing and slot extraction.
"""

from __future__ import annotations

import warnings

from app.services.runtime.unified_normalizer import get_wareed_normalizer



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
    warnings.warn(
        "app.utils.text_normalize.normalize_text() is deprecated. "
        "Use WareedNormalizer.normalize() from unified_normalizer.",
        DeprecationWarning,
        stacklevel=2,
    )
    return get_wareed_normalizer().normalize(text or "")
