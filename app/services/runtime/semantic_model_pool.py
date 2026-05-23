"""Shared SentenceTransformer instance pool for runtime semantic search."""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

logger = logging.getLogger(__name__)


def lab_rag_v2_enabled() -> bool:
    """True when Lab RAG v2 (OpenAI embeddings) is active.

    When enabled, the legacy local sentence-transformers model is redundant and
    must NOT be loaded (~500MB RAM; caused OOM on Render).
    """
    val = os.getenv("USE_LAB_RAG_V2")
    if val is not None:
        return str(val).strip().lower() in ("1", "true", "yes", "on")
    try:
        from app.core.config import settings
        return bool(getattr(settings, "USE_LAB_RAG_V2", False))
    except Exception:
        return False

_MODEL_SINGLETONS: dict[str, Any] = {}
_TORCH_THREADS_CONFIGURED = False
_MODEL_INIT_LOCK = threading.Lock()


def get_shared_sentence_transformer(model_name: str):
    """Return a process-wide shared SentenceTransformer instance."""
    global _TORCH_THREADS_CONFIGURED
    model_key = str(model_name or "").strip()
    if not model_key:
        raise ValueError("model_name must be a non-empty string")

    # Skip loading the heavy local model entirely when Lab RAG v2 is active.
    if lab_rag_v2_enabled():
        logger.info("sentence-transformers load skipped (USE_LAB_RAG_V2=true) | model=%s", model_key)
        return None

    cached = _MODEL_SINGLETONS.get(model_key)
    if cached is not None:
        return cached

    with _MODEL_INIT_LOCK:
        cached = _MODEL_SINGLETONS.get(model_key)
        if cached is not None:
            return cached

        try:
            import torch  # type: ignore

            if not _TORCH_THREADS_CONFIGURED:
                torch.set_num_threads(1)
                _TORCH_THREADS_CONFIGURED = True
        except Exception as exc:
            logger.debug("torch threading cap not applied | reason=%s", exc.__class__.__name__)

        from sentence_transformers import SentenceTransformer  # type: ignore

        model = SentenceTransformer(model_key)
        _MODEL_SINGLETONS[model_key] = model
        logger.info("semantic model loaded once | model=%s", model_key)
        return model
