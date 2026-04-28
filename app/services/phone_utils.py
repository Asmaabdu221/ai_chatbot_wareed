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
_PHONE_RE = re.compile(r"(?<!\d)(\+?(?:00)?\d{9,14})(?!\d)")


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
    if not text:
        return None
    cleaned = normalize_phone(text)
    if not cleaned:
        return None

    if cleaned.startswith("+"):
        if not re.fullmatch(r"\+9665\d{8}", cleaned):
            return None
        return cleaned

    if not cleaned.isdigit():
        return None

    if re.fullmatch(r"050\d{7}", cleaned):
        return f"+966{cleaned[1:]}"
    if re.fullmatch(r"50\d{7}", cleaned):
        return f"+966{cleaned}"
    if re.fullmatch(r"96650\d{7}", cleaned):
        return f"+{cleaned}"
    if re.fullmatch(r"0096650\d{7}", cleaned):
        return f"+{cleaned[2:]}"
    return None


def detect_phone(text: str) -> str | None:
    text = _to_western(_safe_text(text))
    for m in _PHONE_RE.finditer(text):
        normalized = normalize_saudi_mobile_phone(m.group(1))
        if normalized:
            return normalized
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
