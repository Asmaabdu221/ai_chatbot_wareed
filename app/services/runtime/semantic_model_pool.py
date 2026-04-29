"""Shared SentenceTransformer instance pool for runtime semantic search."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_MODEL_SINGLETONS: dict[str, Any] = {}
_TORCH_THREADS_CONFIGURED = False


def get_shared_sentence_transformer(model_name: str):
    """Return a process-wide shared SentenceTransformer instance."""
    global _TORCH_THREADS_CONFIGURED
    model_key = str(model_name or "").strip()
    if not model_key:
        raise ValueError("model_name must be a non-empty string")

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
    return model

