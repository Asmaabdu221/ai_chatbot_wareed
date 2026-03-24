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

from app.services.runtime.branches_resolver import resolve_branches_query
from app.services.runtime.branches_semantic_intent import (
    detect_branch_semantic_intent,
    is_confident_branch_intent,
)
from app.services.runtime.faq_resolver import resolve_faq
from app.services.runtime.packages_resolver import resolve_packages_query
from app.services.runtime.runtime_fallbacks import (
    get_faq_no_match_message,
    get_out_of_scope_message,
    get_rebuild_mode_message,
)

logger = logging.getLogger(__name__)
ENABLE_BRANCHES_RUNTIME_AFTER_FAQ = True
ENABLE_PACKAGES_RUNTIME_AFTER_BRANCHES = True


def _safe_str(value: Any) -> str:
    """Convert any value to a safely stripped string."""
    return str(value or "").strip()


def route_runtime_message(
    user_text: str,
    *,
    system_rebuild_mode: bool = False,
    faq_only_runtime_mode: bool = False,
    last_user_text: str = "",
    last_assistant_text: str = "",
    recent_runtime_messages: list[dict[str, Any]] | None = None,
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
        faq_result = resolve_faq(
            text,
            last_user_text=last_user_text,
            last_assistant_text=last_assistant_text,
            recent_runtime_messages=recent_runtime_messages,
        )
        if faq_result:
            logger.debug(
                "faq_only route matched | q=%s | selected_faq_id=%s | matched_text=%s | route=faq_only",
                text,
                _safe_str(faq_result.get("faq_id")),
                _safe_str(faq_result.get("matched_text")),
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

        logger.debug(
            "faq_only no match | q=%s | route=faq_only_no_match",
            text,
        )
        semantic_intent = ""
        semantic_score = 0.0
        semantic_routing_used = False
        if ENABLE_BRANCHES_RUNTIME_AFTER_FAQ:
            semantic_result = detect_branch_semantic_intent(text)
            semantic_intent = _safe_str(semantic_result.get("intent"))
            semantic_score = float(semantic_result.get("score") or 0.0)
            semantic_routing_used = is_confident_branch_intent(semantic_result)

            branches_result = resolve_branches_query(text)
            if bool(branches_result.get("matched")):
                logger.debug(
                    "branches route matched after faq no match | q=%s | route=%s | semantic_intent=%s | semantic_score=%.4f | semantic_routing_used=%s",
                    text,
                    _safe_str(branches_result.get("route")),
                    semantic_intent,
                    semantic_score,
                    semantic_routing_used,
                )
                meta = dict(branches_result.get("meta") or {})
                meta["semantic_intent"] = semantic_intent
                meta["semantic_score"] = semantic_score
                meta["semantic_routing_used"] = semantic_routing_used
                return {
                    "reply": _safe_str(branches_result.get("answer")),
                    "route": _safe_str(branches_result.get("route")) or "branches",
                    "source": "branches",
                    "matched": True,
                    "meta": meta,
                }

            if ENABLE_PACKAGES_RUNTIME_AFTER_BRANCHES:
                packages_result = resolve_packages_query(text)
                if bool(packages_result.get("matched")):
                    logger.debug(
                        "packages route matched after faq/branches no match | q=%s | route=%s",
                        text,
                        _safe_str(packages_result.get("route")),
                    )
                    return {
                        "reply": _safe_str(packages_result.get("answer")),
                        "route": _safe_str(packages_result.get("route")) or "packages",
                        "source": "packages",
                        "matched": True,
                        "meta": dict(packages_result.get("meta") or {}),
                    }
        return {
            "reply": get_faq_no_match_message(),
            "route": "faq_only_no_match",
            "source": "runtime_fallback",
            "matched": False,
            "meta": {
                "mode": "faq_only",
                "semantic_intent": semantic_intent,
                "semantic_score": semantic_score,
                "semantic_routing_used": semantic_routing_used,
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
    last_user_text: str = "",
    last_assistant_text: str = "",
    recent_runtime_messages: list[dict[str, Any]] | None = None,
) -> str:
    """Return only the final reply text for the current runtime stage."""
    result = route_runtime_message(
        user_text,
        system_rebuild_mode=system_rebuild_mode,
        faq_only_runtime_mode=faq_only_runtime_mode,
        last_user_text=last_user_text,
        last_assistant_text=last_assistant_text,
        recent_runtime_messages=recent_runtime_messages,
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
