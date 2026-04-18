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

import re
from typing import Optional

# Eastern Arabic → Western Arabic
_EASTERN_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

# Greedy pattern: optional leading +/00, then 9–13 contiguous digits
_PHONE_RE = re.compile(r"(?<!\d)(\+?(?:00)?\d{9,13})(?!\d)")


def _to_western(text: str) -> str:
    return text.translate(_EASTERN_DIGITS)


def normalize_phone(raw: str) -> str:
    """Strip all non-digit/+ chars after digit normalization."""
    return re.sub(r"[^\d+]", "", _to_western(raw or ""))


def _digits_only(value: str) -> str:
    return re.sub(r"\D", "", value)


def _is_valid(normalized: str) -> bool:
    """Return True only for well-formed mobile numbers."""
    if not normalized:
        return False
    digits = _digits_only(normalized)
    n = len(digits)
    if not (9 <= n <= 14):
        return False

    # Saudi local 05XXXXXXXX (10 digits)
    if re.fullmatch(r"05\d{8}", digits):
        return True

    # Saudi local 5XXXXXXXX (9 digits)
    if re.fullmatch(r"5\d{8}", digits):
        return True

    # Saudi international +9665XXXXXXXX (12 digits) or 009665XXXXXXXX (14 digits)
    if re.fullmatch(r"9665\d{8}", digits):
        return True
    if re.fullmatch(r"009665\d{8}", digits):
        return True

    # Generic international: + prefix required, 10-14 total digits
    if normalized.startswith("+") and 10 <= n <= 14:
        return True

    return False


def extract_phone(text: str) -> Optional[str]:
    """
    Extract the first valid phone number from *text*.

    Returns the normalized form (digits + optional leading +), or None.
    Rejects messages with more than 8 whitespace tokens (likely a sentence).
    """
    if not text:
        return None

    western = _to_western(text.strip())

    # Conservative: if the message looks like a sentence, don't mine it for numbers
    if len(western.split()) > 8:
        return None

    for match in _PHONE_RE.findall(western):
        candidate = normalize_phone(match)
        if _is_valid(candidate):
            return candidate

    return None


def is_phone_message(text: str) -> bool:
    """True when *text* appears to be primarily a phone number submission."""
    return extract_phone(text) is not None
