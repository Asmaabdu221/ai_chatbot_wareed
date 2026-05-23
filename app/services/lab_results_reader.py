"""
Uploaded lab-results reader (Feature 1).

Takes the text extracted from an uploaded image/PDF (via the existing OCR /
document-extraction services) and turns it into a structured, customer-facing
list of the tests we recognised, with three-state availability:

  * ✅  is_available == "متاح / Yes"          -> "متوفر عندنا"
  * ⚠️  matched but is_available == NEEDS_*    -> "نتأكد لك"
  * ❌  looks like a test but not in catalog   -> "غير متوفر حالياً"

Matching reuses the Lab RAG v2 SynonymRetriever (Layer 1). This module never
raises into the chat path: any failure returns None so the caller falls back
to existing behaviour.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# ---- customer-facing copy ---------------------------------------------------
OCR_UNREADABLE_MSG = (
    "ما قدرت أقرأ الورقة بوضوح 😅\n"
    "جرب ترفع صورة أوضح، أو اكتب أسماء التحاليل يدوياً"
)
_DISCLAIMER = "هذي معلومات إرشادية عامة — فريقنا الطبي يقدر يساعدك أكثر"
_LEAD_CTA = (
    "للاستفسار عن أسعار هذي التحاليل أو حجز موعد،\n"
    "اكتب رقم جوالك وفريقنا يتواصل معك 📞"
)
_HEADER = "قرأت الورقة اللي رفعتها 📋\nوجدت هذي التحاليل:"

_STATUS_AVAILABLE = "متوفر عندنا"
_STATUS_REVIEW = "نتأكد لك"
_STATUS_UNAVAILABLE = "غير متوفر حالياً"

# limits to keep the reply readable and avoid OCR-noise floods
_MAX_MATCHED = 12
_MAX_UNMATCHED = 3

_SEP = re.compile(r"[,،;/|\n\r\t]+")
_LETTER = re.compile(r"[A-Za-z؀-ۿ]")
_DIGIT = re.compile(r"\d")

_UNITS = {
    "mg", "ng", "ml", "dl", "l", "g", "u", "iu", "miu", "mmol", "umol", "mol",
    "pg", "fl", "ph", "ratio", "cells", "mcg", "ug", "nmol", "pmol", "ku", "k",
}
_QUALIFIERS = {"high", "low", "normal", "h", "l", "positive", "negative", "pos", "neg"}
_HEADER_WORDS = {
    "report", "lab", "laboratory", "patient", "name", "date", "age", "sex",
    "gender", "result", "results", "reference", "range", "unit", "units",
    "sample", "page", "tel", "phone", "address", "doctor", "clinic", "hospital",
    "total", "value", "comment", "method", "id", "time", "mrn", "no",
    "collected", "received", "printed", "final", "specimen", "test", "tests",
}
_DECIMAL = re.compile(r"^[<>]?\d+[.,]\d+$")


def _strip_trailing_noise(s: str) -> str:
    """Drop trailing result values/units (12.3, ng, mL, High) but keep integers
    that are part of names (CA 125, B12)."""
    toks = s.split()
    while toks:
        raw = toks[-1]
        t = raw.strip(".:%()[]<>/,").lower()
        if (
            t == ""
            or t in _UNITS
            or t in _QUALIFIERS
            or _DECIMAL.match(raw.strip("%()[]<>/,"))
        ):
            toks.pop()
        else:
            break
    return " ".join(toks)


def _is_headerish(s: str) -> bool:
    toks = [t.strip(".:()[]").lower() for t in s.split()]
    toks = [t for t in toks if t]
    if not toks:
        return True
    hits = sum(1 for t in toks if t in _HEADER_WORDS)
    return hits > 0 and hits >= len(toks) / 2


def _candidates(text: str) -> list[str]:
    """Split extracted text into de-duplicated candidate test-name fragments."""
    out: list[str] = []
    seen: set[str] = set()
    for part in _SEP.split(text or ""):
        s = " ".join(part.split())  # collapse whitespace
        if len(s) < 2 or len(s) > 60:
            continue
        toks = s.split()
        if len(toks) > 6:  # too long to be a name; keep the leading tokens
            s = " ".join(toks[:6])
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def _looks_like_test_name(s: str) -> bool:
    """Conservative check that an unmatched fragment resembles a test name."""
    letters = _LETTER.findall(s)
    if len(letters) < 3:
        return False
    digits = _DIGIT.findall(s)
    if digits and len(digits) > len(letters):  # mostly a value/units line
        return False
    return True


def _avail_state(row: dict) -> str:
    v = str(row.get("is_available", "")).strip().lower()
    if not v or v.startswith("needs"):
        return "review"
    if any(tok in v for tok in ("yes", "متاح", "available", "نعم")):
        return "yes"
    return "review"


def _display_name(row: dict, fallback: str = "") -> str:
    from app.data.lab_data_loader import COL_NAME_AR, COL_NAME_EN
    ar = str(row.get(COL_NAME_AR, "")).strip()
    en = str(row.get(COL_NAME_EN, "")).strip()
    if en and ar:
        return f"{en} - {ar}"
    return en or ar or fallback


def read_lab_results_from_text(text: str) -> str | None:
    """Build the structured lab-results reply, or None if nothing was matched."""
    try:
        if not (text or "").strip():
            return None
        from app.services.lab_retrieval_engine import get_lab_retrieval_engine
        from app.data.lab_data_loader import COL_ID

        engine = get_lab_retrieval_engine()
        if getattr(engine, "synonym_retriever", None) is None:
            engine.warm_up()
        retriever = engine.synonym_retriever
        if retriever is None:
            return None

        matched_ids: list[str] = []
        seen_ids: set[str] = set()
        unmatched: list[str] = []
        for cand in _candidates(text):
            probe = _strip_trailing_noise(cand) or cand
            ids = retriever.search(probe, threshold=85)
            if ids:
                tid = str(ids[0]).strip()
                if tid and tid not in seen_ids:
                    seen_ids.add(tid)
                    matched_ids.append(tid)
            elif (
                _looks_like_test_name(probe)
                and not _is_headerish(probe)
                and len(unmatched) < _MAX_UNMATCHED
            ):
                unmatched.append(probe)

        if not matched_ids:
            return None  # not a recognisable lab sheet -> let existing flow handle it

        rows = engine.data_loader.get_tests_by_ids(matched_ids[:_MAX_MATCHED])
        lines = [_HEADER, ""]
        for row in rows:
            state = _avail_state(row)
            if state == "yes":
                lines.append(f"✅ {_display_name(row)} ({_STATUS_AVAILABLE})")
            else:
                lines.append(f"⚠️ {_display_name(row)} ({_STATUS_REVIEW})")
        for cand in unmatched:
            lines.append(f"❌ {cand} ({_STATUS_UNAVAILABLE})")

        lines += ["", _DISCLAIMER, "", _LEAD_CTA]
        return "\n".join(lines)
    except Exception as exc:  # never break the chat path
        logger.warning("lab_results_reader skipped (non-blocking): %s", exc)
        return None
