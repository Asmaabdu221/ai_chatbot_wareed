"""Unified Arabic-first normalization service for Wareed runtime/data paths."""

from __future__ import annotations

import json
import logging
import re
import time
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)


class WareedNormalizer:
    """Single source of truth for text normalization across runtime/data paths."""

    _ARABIC_DIACRITICS_RE = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]")
    _PUNCT_NOISE_RE = re.compile(r"[^A-Za-z0-9\u0660-\u0669\u06F0-\u06F9\u0621-\u063A\u0641-\u064A\s]")
    _MULTISPACE_RE = re.compile(r"\s+")

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
    _ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
    _PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")

    # Fallback colloquial replacements, used when runtime synonyms file is absent.
    _FALLBACK_COLLOQUIAL_REPLACEMENTS: tuple[tuple[str, str], ...] = (
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
        ("تحاليلك", "التحاليل"),
        ("تحاليللي", "التحاليل"),
        ("في البيت", "المنزل"),
        ("للبيت", "المنزل"),
        ("سحب منزلي", "الزيارات المنزلية"),
        ("زيارة منزلية", "الزيارات المنزلية"),
    )

    def __init__(self, *, synonyms_path: Path | None = None) -> None:
        self._synonyms_path = synonyms_path or Path("app/data/runtime/synonyms/synonyms_ar.json")

    @lru_cache(maxsize=1)
    def _colloquial_replacements(self) -> tuple[tuple[str, str], ...]:
        pairs: list[tuple[str, str]] = []
        if self._synonyms_path.exists():
            try:
                payload = json.loads(self._synonyms_path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    for canonical, variants in payload.items():
                        canonical_s = str(canonical or "").strip()
                        if not canonical_s:
                            continue
                        if isinstance(variants, list):
                            for variant in variants:
                                variant_s = str(variant or "").strip()
                                if variant_s:
                                    pairs.append((variant_s, canonical_s))
            except Exception:
                logger.debug("wareed_normalizer failed loading synonyms map", exc_info=True)

        if not pairs:
            pairs = list(self._FALLBACK_COLLOQUIAL_REPLACEMENTS)

        # Normalize replacement terms themselves and keep longest-first for stable substitution.
        normalized_pairs: list[tuple[str, str]] = []
        for src, dst in pairs:
            src_n = self._normalize_core(src)
            dst_n = self._normalize_core(dst)
            if src_n and dst_n:
                normalized_pairs.append((src_n, dst_n))
        normalized_pairs.sort(key=lambda x: len(x[0]), reverse=True)
        # Deduplicate by source.
        dedup: dict[str, str] = {}
        for src, dst in normalized_pairs:
            dedup.setdefault(src, dst)
        return tuple(dedup.items())

    def _normalize_core(self, text: str) -> str:
        value = str(text or "")
        if not value:
            return ""
        value = value.strip().lower()
        if not value:
            return ""
        # Order required by specification.
        value = value.translate(self._CHAR_NORMALIZATION)
        value = self._ARABIC_DIACRITICS_RE.sub("", value).replace("ـ", "")
        value = value.translate(self._ARABIC_DIGITS).translate(self._PERSIAN_DIGITS)
        value = self._PUNCT_NOISE_RE.sub(" ", value)
        value = self._MULTISPACE_RE.sub(" ", value).strip()
        return value

    @staticmethod
    def _is_significant_change(original: str, normalized: str) -> bool:
        if not original:
            return False
        if original == normalized:
            return False
        # avoid noisy logs on tiny cosmetic changes
        return abs(len(original) - len(normalized)) >= 2 or len(original) >= 12

    def normalize(self, text: str) -> str:
        """Normalize input using unified Wareed pipeline."""
        started = time.perf_counter()
        original = str(text or "")
        core_value = self._normalize_core(original)
        value = core_value
        colloquial_match = False
        if value:
            padded = f" {value} "
            for src, dst in self._colloquial_replacements():
                if src and dst and f" {src} " in padded:
                    padded = padded.replace(f" {src} ", f" {dst} ")
                    colloquial_match = True
            value = self._MULTISPACE_RE.sub(" ", padded).strip()

        if self._is_significant_change(original.strip(), value):
            if colloquial_match:
                change_type = "colloquial_match"
            elif core_value != original.strip().lower():
                change_type = "character_standardized"
            else:
                change_type = "normalized"
            processing_time_ms = round((time.perf_counter() - started) * 1000, 3)
            payload = {
                "event": "wareed_normalization",
                "original_text": original[:180],
                "normalized_text": value[:180],
                "change_type": change_type,
                "processing_time_ms": processing_time_ms,
            }
            logger.debug(payload)
        return value


_WAREED_NORMALIZER = WareedNormalizer()


def get_wareed_normalizer() -> WareedNormalizer:
    return _WAREED_NORMALIZER
