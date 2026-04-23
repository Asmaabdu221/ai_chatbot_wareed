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


def detect_phone(text: str) -> str | None:
    text = text.strip()
    match = re.search(r'(?:\+?966|0)?5\d{8}', text)
    if match:
        return match.group()
    return None


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
