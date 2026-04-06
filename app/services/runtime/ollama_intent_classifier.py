"""Safe Ollama intent classifier for runtime routing assistance only."""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request
from typing import Any

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/api").rstrip("/")
OLLAMA_URL = f"{OLLAMA_BASE_URL}/generate"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_FORMATTER_MODEL = os.getenv("OLLAMA_FORMATTER_MODEL", OLLAMA_MODEL)
REQUEST_TIMEOUT_SECONDS = 15

_ALLOWED_INTENTS = {"test", "package", "branch", "faq", "symptoms", "results", "unknown"}

_FALLBACK_LABEL = "unknown"
logger = logging.getLogger(__name__)

_SYSTEM_PROMPT_TEMPLATE = """You are an intent classifier for a medical lab assistant.

Return ONLY one lowercase label with no punctuation and no explanation.

Allowed intents:
test, package, branch, faq, symptoms, results, unknown

Rules:
- Output exactly one label from the allowed list.
- If uncertain, output unknown.

User message:
{user_text}
"""

_FORMATTER_PROMPT_TEMPLATE = """You are a formatter, not a generator.

Your job is ONLY to clean and rewrite the text into a natural, human-friendly Arabic message as if it is coming directly from Wareed Lab.

STRICT RULES:
- Speak in first-person plural voice (نحن / نقدم / نوفر / عندنا)
- Do NOT sound like a third party
- Do NOT say "المختبر يقدم" -> say "نحن نقدم"
- Do NOT add any new information
- Do NOT explain anything
- Do NOT repeat sentences
- Do NOT add sections like "عنوان" or "وصف"
- Do NOT mention rewriting or formatting
- Do NOT add extra commentary
- Do NOT change meaning

FORMAT:
- One clean title line (optional emoji allowed)
- Then a short clean paragraph
- Bullet points only if they already exist in the input

STYLE:
- Natural Arabic
- Saudi-friendly tone (natural, simple, not slang-heavy)
- Warm and helpful
- Clear and confident
- Short and clear

TONE EXAMPLES:
- "نحن نقدم لك..."
- "هذه الباقة تساعدك على..."
- "تقدر تسوي التحليل بكل سهولة..."
- "ما يحتاج صيام..."

IMPORTANT:
If the text is already clean -> return it as-is.

Input:
{raw_text}

Output:
Final clean response ONLY.
"""


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _extract_json_object(text: str) -> dict[str, Any] | None:
    value = _safe_str(text)
    if not value:
        return None

    # Try direct JSON first.
    try:
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # Fallback: extract first JSON object block.
    match = re.search(r"\{[\s\S]*\}", value)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        return None
    return None


def _extract_intent_label(text: str) -> str:
    value = _safe_str(text).lower()
    if not value:
        return _FALLBACK_LABEL

    # Direct label.
    if value in _ALLOWED_INTENTS:
        return value

    # JSON object fallback.
    parsed = _extract_json_object(value)
    if isinstance(parsed, dict):
        candidate = _safe_str(parsed.get("intent")).lower()
        if candidate in _ALLOWED_INTENTS:
            return candidate

    # Regex fallback inside free text.
    match = re.search(r"\b(test|package|branch|faq|symptoms|results|unknown)\b", value)
    if match:
        return _safe_str(match.group(1)).lower()
    return _FALLBACK_LABEL


def classify_intent_label(user_text: str) -> str:
    """Classify user query to one allowed label using local Ollama."""
    message = _safe_str(user_text)
    if not message:
        logger.debug("ollama classifier empty_query -> returning unknown")
        return _FALLBACK_LABEL

    prompt = _SYSTEM_PROMPT_TEMPLATE.format(user_text=message)
    body = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
    }

    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    logger.debug(
        "ollama classifier config | base_url=%s | model=%s | request_url=%s | timeout_seconds=%s",
        OLLAMA_BASE_URL,
        OLLAMA_MODEL,
        OLLAMA_URL,
        REQUEST_TIMEOUT_SECONDS,
    )
    logger.debug(
        "ollama classifier request | query_len=%s",
        len(message),
    )

    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            raw = resp.read().decode("utf-8")
        logger.debug(
            "ollama classifier raw_response_snippet=%s",
            _safe_str(raw).replace("\n", " ")[:200],
        )
        outer = json.loads(raw)
        response_text = _safe_str((outer or {}).get("response"))
        extracted = _extract_intent_label(response_text)
        logger.debug(
            "ollama classifier parsed_response_snippet=%s | extracted_label=%s",
            response_text.replace("\n", " ")[:200],
            extracted,
        )
        if extracted == _FALLBACK_LABEL:
            logger.debug(
                "ollama classifier label_extraction_unrecognized | response_snippet=%s",
                response_text.replace("\n", " ")[:200],
            )
        return extracted
    except urllib.error.HTTPError as exc:
        logger.exception(
            "ollama classifier http_error | status=%s | reason=%s",
            getattr(exc, "code", ""),
            getattr(exc, "reason", ""),
        )
        logger.debug(
            "classify_intent_label failed -> returning unknown | error_type=%s | error=%s",
            type(exc).__name__,
            _safe_str(exc),
        )
        return _FALLBACK_LABEL
    except urllib.error.URLError as exc:
        logger.exception("ollama classifier url_error | reason=%s", getattr(exc, "reason", ""))
        logger.debug(
            "classify_intent_label failed -> returning unknown | error_type=%s | error=%s",
            type(exc).__name__,
            _safe_str(exc),
        )
        return _FALLBACK_LABEL
    except TimeoutError as exc:
        logger.exception("ollama classifier timeout_error")
        logger.debug(
            "classify_intent_label failed -> returning unknown | error_type=%s | error=%s",
            type(exc).__name__,
            _safe_str(exc),
        )
        return _FALLBACK_LABEL
    except json.JSONDecodeError as exc:
        logger.exception("ollama classifier json_decode_error")
        logger.debug(
            "classify_intent_label failed -> returning unknown | error_type=%s | error=%s",
            type(exc).__name__,
            _safe_str(exc),
        )
        return _FALLBACK_LABEL
    except (ValueError, OSError) as exc:
        logger.exception("ollama classifier runtime_error")
        logger.debug(
            "classify_intent_label failed -> returning unknown | error_type=%s | error=%s",
            type(exc).__name__,
            _safe_str(exc),
        )
        return _FALLBACK_LABEL


def format_final_response_with_ollama(raw_text: str) -> str:
    """Rewrite final deterministic response for cleaner UX without changing facts."""
    message = _safe_str(raw_text)
    if not message:
        return message

    prompt = _FORMATTER_PROMPT_TEMPLATE.format(raw_text=message)
    body = {
        "model": OLLAMA_FORMATTER_MODEL,
        "prompt": prompt,
        "stream": False,
    }
    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    logger.debug(
        "ollama formatter request | model=%s | request_url=%s | timeout_seconds=%s | raw_len=%s",
        OLLAMA_FORMATTER_MODEL,
        OLLAMA_URL,
        REQUEST_TIMEOUT_SECONDS,
        len(message),
    )
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            raw = resp.read().decode("utf-8")
        outer = json.loads(raw)
        response_text = _safe_str((outer or {}).get("response"))
        if not response_text:
            logger.debug("ollama formatter empty_response -> keep_raw")
            return message
        logger.debug("ollama formatter success | rewritten_len=%s", len(response_text))
        return response_text
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
        ValueError,
        OSError,
    ) as exc:
        logger.debug(
            "ollama formatter failed -> keep_raw | error_type=%s | error=%s",
            type(exc).__name__,
            _safe_str(exc),
        )
        return message


def _validate_output(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"intent": _FALLBACK_LABEL}

    intent = _safe_str(payload.get("intent")).lower()
    if intent not in _ALLOWED_INTENTS:
        intent = _FALLBACK_LABEL
    return {"intent": intent}


def classify_intent(user_text: str, context: dict) -> dict:
    """Backward-compatible wrapper returning dict with `intent` only."""
    _ = context  # reserved for future safe context-aware classification
    return _validate_output({"intent": classify_intent_label(user_text)})
