"""
Embeddings Service - OpenAI Embeddings API
==========================================
Provides text embeddings for semantic search using OpenAI's embedding API.
"""

import logging
from typing import List, Union

from app.core.config import settings

logger = logging.getLogger(__name__)

# Lazy client to avoid import errors when OpenAI is not configured
_client = None


def _get_client():
    global _client
    if _client is None:
        try:
            from openai import OpenAI
            # Keep embedding calls fast-fail so RAG can gracefully fall back to lexical/KB search.
            _client = OpenAI(
                api_key=settings.OPENAI_API_KEY,
                timeout=8.0,
                max_retries=0,
            )
        except Exception as e:
            logger.warning("OpenAI client not available for embeddings: %s", e)
    return _client


def get_embedding(text: str) -> List[float]:
    """
    Get embedding vector for a single text using OpenAI API.

    Args:
        text: Input text (will be stripped; empty returns zero vector).

    Returns:
        List of floats (embedding vector), or empty list on error.
    """
    text = (text or "").strip()
    if not text:
        return []
    try:
        client = _get_client()
        if not client:
            return []
        response = client.embeddings.create(
            model=settings.OPENAI_EMBEDDING_MODEL,
            input=text,
        )
        return list(response.data[0].embedding)
    except Exception as e:
        logger.exception("Embedding API error: %s", e)
        return []


def get_embeddings(texts: List[str], batch_size: int = 100) -> List[List[float]]:
    """
    Get embedding vectors for multiple texts (batched).

    Args:
        texts: List of input texts.
        batch_size: Max items per API call (OpenAI limit is high; we use 100).

    Returns:
        List of embedding vectors (same order as texts). Failed items get [].
    """
    if not texts:
        return []
    results = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        # Keep order: use space for empty so API returns same count
        to_send = [(t or "").strip() or " " for t in batch]
        try:
            client = _get_client()
            if not client:
                results.extend([[]] * len(batch))
                continue
            response = client.embeddings.create(
                model=settings.OPENAI_EMBEDDING_MODEL,
                input=to_send,
            )
            for d in response.data:
                results.append(list(d.embedding))
        except Exception as e:
            logger.exception("Batch embedding error: %s", e)
            results.extend([[]] * len(batch))
    return results
