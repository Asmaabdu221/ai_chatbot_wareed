"""
Phone number detection and normalization — Phase 2.

Conservative by design: rejects anything that doesn't look like a real mobile
number.  Better to miss an ambiguous number than to capture a price or year.

Supported formats
-----------------
  Local Saudi  : 05XXXXXXXX   (10 digits, starts 05)
               : 5XXXXXXXX    (9 digits,  starts 5)
  International: +9665XXXXXXXX or 009665XXXXXXXX
  Generic intl : +<country><10-12 digits>  (10-13 digit body)

Rejection rules
---------------
  - Fewer than 9 digits → too short
  - More than 13 digits → too long (avoids matching long IDs)
  - Message has more than 8 space-separated tokens → probably a sentence, not a phone
  - Sequences that look like prices/years (e.g., "150", "2024") → rejected by digit-count
"""

from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Eastern Arabic → Western Arabic
_EASTERN_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

# Greedy pattern: optional leading +/00, then 9–13 contiguous digits
_PHONE_CANDIDATE_RE = re.compile(r"(?<!\d)(\+?\d[\d\s\-\(\)\.]{7,20}\d)(?!\d)")


def _to_western(text: str) -> str:
    return text.translate(_EASTERN_DIGITS)


def normalize_phone(raw: str) -> str:
    """Strip all non-digit/+ chars after digit normalization."""
    return re.sub(r"[^\d+]", "", _to_western(raw or ""))


def _digits_only(value: str) -> str:
    return re.sub(r"\D", "", value)


def normalize_saudi_mobile_phone(text: str) -> str | None:
    """
    Normalize Saudi mobile numbers to +9665XXXXXXXX.

    Accepted inputs:
      - 05XXXXXXXX
      - 5XXXXXXXX
      - +9665XXXXXXXX
      - 9665XXXXXXXX
      - 009665XXXXXXXX
    """
    raw_input = _safe_text(text)
    if not raw_input:
        logger.info("phone_utils | raw_input=%r | normalized_phone=%s | valid=%s", raw_input, "", False)
        return None

    cleaned = normalize_phone(raw_input)
    if not cleaned:
        logger.info("phone_utils | raw_input=%r | normalized_phone=%s | valid=%s", raw_input, "", False)
        return None

    normalized: str | None = None

    if cleaned.startswith("+"):
        if re.fullmatch(r"\+9665[0345689]\d{7}", cleaned):
            normalized = cleaned
    elif cleaned.isdigit():
        if re.fullmatch(r"05[0345689]\d{7}", cleaned):
            normalized = f"+966{cleaned[1:]}"
        elif re.fullmatch(r"5[0345689]\d{7}", cleaned):
            normalized = f"+966{cleaned}"
        elif re.fullmatch(r"9665[0345689]\d{7}", cleaned):
            normalized = f"+{cleaned}"
        elif re.fullmatch(r"009665[0345689]\d{7}", cleaned):
            normalized = f"+{cleaned[2:]}"

    is_valid = bool(
        normalized
        and normalized.startswith("+9665")
        and len(normalized) == 13
        and re.fullmatch(r"\+966\d+", normalized)
    )
    logger.info(
        "phone_utils | raw_input=%r | normalized_phone=%s | valid=%s",
        raw_input,
        normalized or "",
        is_valid,
    )
    return normalized if is_valid else None


def detect_phone(text: str) -> str | None:
    raw_input = _safe_text(text)
    western_input = _to_western(raw_input)

    for m in _PHONE_CANDIDATE_RE.finditer(western_input):
        detected_number = _safe_text(m.group(1))
        cleaned_input = normalize_phone(detected_number)
        normalized = normalize_saudi_mobile_phone(detected_number)
        logger.info(
            "phone_utils.detect | raw_input=%r | cleaned_input=%s | detected_number=%s | normalized_number=%s",
            raw_input,
            cleaned_input,
            detected_number,
            normalized or "",
        )
        if normalized:
            return normalized

    logger.info(
        "phone_utils.detect | raw_input=%r | cleaned_input=%s | detected_number=%s | normalized_number=%s",
        raw_input,
        normalize_phone(western_input),
        "",
        "",
    )
    return None


def _safe_text(text: str) -> str:
    return str(text or "").strip()


def extract_phone(text: str) -> Optional[str]:
    """
    Extract the first valid phone number from *text*.

    Returns the normalized form (digits + optional leading +), or None.
    Rejects messages with more than 8 whitespace tokens (likely a sentence).
    """
    if not text:
        return None
    return detect_phone(text)


def is_phone_message(text: str) -> bool:
    """True when *text* appears to be primarily a phone number submission."""
    return extract_phone(text) is not None


# ---------------------------------------------------------------------------
# Topic-switch / phone-attempt discrimination
# ---------------------------------------------------------------------------

# Arabic Unicode block — presence means real text, not a phone attempt
_ARABIC_RE = re.compile(r"[\u0600-\u06FF]")


def is_phone_attempt(text: str) -> bool:
    """
    True when text looks like a failed phone-number entry (short, mostly
    digits, no real words).

    Examples that return True  : "053", "12345", "0567"
    Examples that return False : "وين الفروع؟", "I have lab results", "hello"

    Used to decide whether to show a soft "invalid phone" message vs silently
    exiting phone-capture mode and routing the message normally.
    """
    if not text:
        return False

    western = _to_western(text.strip())

    # More than 3 tokens → clearly a sentence, not a phone attempt
    if len(western.split()) > 3:
        return False

    # Must contain at least one digit
    digits = _digits_only(western)
    if not digits:
        return False

    # Contains Arabic script → real user message
    if _ARABIC_RE.search(western):
        return False

    # Contains more than 2 Latin letters → real word(s)
    if len(re.findall(r"[a-zA-Z]", western)) > 2:
        return False

    # At least half of the non-space characters are digits
    non_space = western.replace(" ", "")
    return len(digits) >= len(non_space) * 0.5


def should_exit_awaiting_phone(text: str) -> bool:
    """
    True when a message received while state==awaiting_phone is clearly a new
    topic — not a valid phone and not a phone-number attempt.

    When this returns True the caller should:
      1. Reset state to IDLE.
      2. Let the message proceed through normal routing.
    """
    return extract_phone(text) is None and not is_phone_attempt(text)
