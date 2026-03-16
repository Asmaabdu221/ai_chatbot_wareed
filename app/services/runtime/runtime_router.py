"""Central runtime router for staged assistant rollout.

Current stage:
- Rebuild mode
- FAQ-only mode

Future stages:
- prices
- branches
- packages
- tests
- site fallback
"""

from __future__ import annotations

import logging
from typing import Any

from app.services.runtime.faq_resolver import resolve_faq
from app.services.runtime.runtime_fallbacks import (
    get_faq_no_match_message,
    get_out_of_scope_message,
    get_rebuild_mode_message,
)

logger = logging.getLogger(__name__)


def _safe_str(value: Any) -> str:
    """Convert any value to a safely stripped string."""
    return str(value or "").strip()


def _escape_debug(value: Any) -> str:
    """Return unicode-escaped debug-safe text."""
    return _safe_str(value).encode("unicode_escape").decode()


def route_runtime_message(
    user_text: str,
    *,
    system_rebuild_mode: bool = False,
    faq_only_runtime_mode: bool = False,
) -> dict[str, Any]:
    """Route one runtime message according to the currently enabled stage.

    Returns a structured payload that always contains:
    - reply
    - route
    - source
    - matched
    - meta
    """
    text = _safe_str(user_text)

    if system_rebuild_mode:
        return {
            "reply": get_rebuild_mode_message(),
            "route": "rebuild_mode",
            "source": "runtime_fallback",
            "matched": False,
            "meta": {
                "mode": "system_rebuild",
            },
        }

    if faq_only_runtime_mode:
        faq_result = resolve_faq(text)
        if faq_result:
            logger.info(
                "FAQ_ONLY_DEBUG | q=%s | selected_faq_id=%s | matched_text=%s | route=faq_only",
                text,
                _safe_str(faq_result.get("faq_id")),
                _safe_str(faq_result.get("matched_text")),
            )
            print(
                "FAQ_ONLY_DEBUG",
                {
                    "query": _escape_debug(text),
                    "selected_faq_id": _safe_str(faq_result.get("faq_id")),
                    "matched_text": _escape_debug(faq_result.get("matched_text")),
                    "route": "faq_only",
                },
            )
            return {
                "reply": _safe_str(faq_result.get("answer")),
                "route": "faq_only",
                "source": "faq",
                "matched": True,
                "meta": {
                    "faq_id": _safe_str(faq_result.get("faq_id")),
                    "question": _safe_str(faq_result.get("question")),
                    "score": float(faq_result.get("score") or 0.0),
                    "margin": float(faq_result.get("margin") or 0.0),
                    "matched_text": _safe_str(faq_result.get("matched_text")),
                    "concepts": list(faq_result.get("concepts") or []),
                },
            }

        logger.info(
            "FAQ_ONLY_DEBUG | q=%s | selected_faq_id=none | matched_text=none | route=faq_only_no_match",
            text,
        )
        print(
            "FAQ_ONLY_DEBUG",
            {
                "query": _escape_debug(text),
                "selected_faq_id": "",
                "matched_text": "",
                "route": "faq_only_no_match",
            },
        )
        return {
            "reply": get_faq_no_match_message(),
            "route": "faq_only_no_match",
            "source": "runtime_fallback",
            "matched": False,
            "meta": {
                "mode": "faq_only",
            },
        }

    return {
        "reply": get_out_of_scope_message(),
        "route": "no_runtime_mode",
        "source": "runtime_fallback",
        "matched": False,
        "meta": {
            "mode": "no_runtime_mode",
        },
    }


def route_runtime_reply(
    user_text: str,
    *,
    system_rebuild_mode: bool = False,
    faq_only_runtime_mode: bool = False,
) -> str:
    """Return only the final reply text for the current runtime stage."""
    result = route_runtime_message(
        user_text,
        system_rebuild_mode=system_rebuild_mode,
        faq_only_runtime_mode=faq_only_runtime_mode,
    )
    return _safe_str(result.get("reply"))


if __name__ == "__main__":
    samples = [
        "وش الخدمات اللي عندكم",
        "عندكم سحب من البيت",
        "وين اقرب فرع بالرياض",
    ]

    print("=== FAQ ONLY MODE ===")
    for sample in samples:
        result = route_runtime_message(
            sample,
            system_rebuild_mode=False,
            faq_only_runtime_mode=True,
        )
        print(f"INPUT : {sample}")
        print(f"ROUTE : {result.get('route')}")
        print(f"SOURCE: {result.get('source')}")
        print(f"MATCH : {result.get('matched')}")
        print(f"REPLY : {result.get('reply')}")
        print(f"META  : {result.get('meta')}")
        print("-" * 80)

    print("=== REBUILD MODE ===")
    result = route_runtime_message(
        "مرحبا",
        system_rebuild_mode=True,
        faq_only_runtime_mode=False,
    )
    print(f"ROUTE : {result.get('route')}")
    print(f"REPLY : {result.get('reply')}")
