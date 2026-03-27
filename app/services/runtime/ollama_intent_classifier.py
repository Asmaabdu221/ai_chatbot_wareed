"""Safe Ollama intent classifier for runtime routing assistance only."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2.5:7b"
REQUEST_TIMEOUT_SECONDS = 15

_ALLOWED_INTENTS = {"test", "package", "branch", "faq", "symptoms", "results", "unknown"}

_FALLBACK: dict[str, Any] = {
    "intent": "unknown",
    "confidence": 0.0,
    "is_followup": False,
}

_SYSTEM_PROMPT_TEMPLATE = """You are an intent classifier for a medical lab assistant.

You must return ONLY valid JSON.

Allowed intents:
test, package, branch, faq, symptoms, results, unknown

Definitions:
- test: question about a lab test (price, fasting, info)
- package: question about packages
- branch: location, branches, cities
- faq: general service questions
- symptoms: user describes symptoms
- results: interpreting lab results

Output format ONLY:

{
  "intent": "...",
  "confidence": 0.0,
  "is_followup": false
}

Rules:
- Do not explain
- Do not add text outside JSON
- Confidence between 0 and 1

User message:
{user_text}
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


def _validate_output(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return dict(_FALLBACK)

    intent = _safe_str(payload.get("intent")).lower()
    if intent not in _ALLOWED_INTENTS:
        intent = "unknown"

    try:
        confidence = float(payload.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    is_followup = bool(payload.get("is_followup", False))

    return {
        "intent": intent,
        "confidence": confidence,
        "is_followup": is_followup,
    }


def classify_intent(user_text: str, context: dict) -> dict:
    """Classify user intent via local Ollama. Never raises; returns safe fallback."""
    _ = context  # reserved for future safe context-aware classification
    message = _safe_str(user_text)
    if not message:
        return dict(_FALLBACK)

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

    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            raw = resp.read().decode("utf-8")
        outer = json.loads(raw)
        response_text = _safe_str((outer or {}).get("response"))
        parsed = _extract_json_object(response_text)
        return _validate_output(parsed)
    except (
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
        ValueError,
        OSError,
    ):
        return dict(_FALLBACK)

