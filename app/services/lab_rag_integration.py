"""
Integration shim for Lab RAG v2 (guarded by the USE_LAB_RAG_V2 flag).

Keeps the new engine isolated from the existing chat pipeline. `chat.py` calls
`maybe_build_lab_context()` only when the feature flag is on; if it returns None,
the caller keeps its existing knowledge_context (so production behaviour is
unchanged while the flag is off).
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def warm_up() -> None:
    """Pre-load the engine + classifier (call at startup when the flag is on)."""
    from app.services.lab_retrieval_engine import get_lab_retrieval_engine
    from app.services.intent_classifier import get_intent_classifier
    get_lab_retrieval_engine()
    get_intent_classifier()


def maybe_build_lab_context(message: str, phone_captured: bool = False) -> Optional[str]:
    """Classify, retrieve, and build a grounded context for a user message.

    Args:
        message: The raw user message.
        phone_captured: Whether the conversation has captured a phone number
            (gates price disclosure). Defaults to False (price never shown).

    Returns:
        A context string to use as ``knowledge_context``, or None if nothing was
        retrieved (so the caller can fall back to its existing context).
    """
    try:
        from app.services.lab_retrieval_engine import get_lab_retrieval_engine
        from app.services.intent_classifier import get_intent_classifier, QueryIntent
        from app.services.context_builder import ContextBuilder

        intent = get_intent_classifier().classify(message)
        result = get_lab_retrieval_engine().retrieve(message, intent)
        if not result.tests and intent != QueryIntent.AMBIGUOUS:
            return None
        ctx = ContextBuilder().build_context(
            tests=result.tests, intent=intent,
            include_price=phone_captured, extra=result.disambiguation,
        )
        return ctx or None
    except Exception as exc:  # never break the chat path
        logger.warning("lab_rag_v2 maybe_build_lab_context skipped: %s", exc)
        return None
