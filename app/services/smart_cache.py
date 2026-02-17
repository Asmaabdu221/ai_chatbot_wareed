"""
Smart Caching System for Chat Responses
========================================
Caches frequent questions/answers to reduce OpenAI API calls and cost.
Supports TTL, stats, optional FAQ preload, and thread-safe in-memory store.

Author: Smart Coding Assistant
Date: 2026-02-05
"""

import hashlib
import re
import logging
import threading
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

# Default: 24 hours
DEFAULT_TTL_HOURS = 24
# Cost per request we avoid (GPT-3.5-turbo approx)
COST_PER_SAVED_REQUEST = 0.00065


def _normalize_question(question: str) -> str:
    """Normalize question for cache key: strip, lower, collapse spaces."""
    if not question or not isinstance(question, str):
        return ""
    text = question.strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def _make_key(question: str) -> str:
    """Generate cache key from normalized question."""
    normalized = _normalize_question(question)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class SmartCache:
    """
    In-memory cache for chat Q&A with TTL and stats.
    Use get() before calling OpenAI; use set() after successful response.
    """

    def __init__(self, ttl_hours: float = DEFAULT_TTL_HOURS, max_entries: int = 50_000):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._ttl = timedelta(hours=ttl_hours)
        self._max_entries = max(1000, max_entries)

        self._hits = 0
        self._misses = 0

    def get(self, question: str) -> Optional[str]:
        """
        Return cached answer if present and not expired.
        Returns None on miss or expired entry.
        """
        key = _make_key(question)
        with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None

            entry = self._cache[key]
            if datetime.utcnow() >= entry["expires_at"]:
                del self._cache[key]
                self._misses += 1
                return None

            self._hits += 1
            return entry["answer"]

    def set(self, question: str, answer: str) -> None:
        """Store answer for question with current TTL."""
        if not question or not answer:
            return

        key = _make_key(question)
        now = datetime.utcnow()
        with self._lock:
            # Evict oldest if at capacity (simple: remove one random/oldest)
            if len(self._cache) >= self._max_entries and key not in self._cache:
                self._evict_one()

            self._cache[key] = {
                "answer": answer,
                "created_at": now,
                "expires_at": now + self._ttl,
                "question_preview": _normalize_question(question)[:80],
            }

    def _evict_one(self) -> None:
        """Remove one expired entry, or the oldest if none expired."""
        now = datetime.utcnow()
        for k, v in list(self._cache.items()):
            if now >= v["expires_at"]:
                del self._cache[k]
                return
        # No expired entry: remove oldest by created_at
        if self._cache:
            oldest_key = min(
                self._cache.keys(),
                key=lambda k: self._cache[k]["created_at"],
            )
            del self._cache[oldest_key]

    def invalidate(self, question: str) -> bool:
        """Remove cache entry for this question. Returns True if removed."""
        key = _make_key(question)
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
        return False

    def clear(self) -> None:
        """Clear all cache entries. Stats (hits/misses) are unchanged."""
        with self._lock:
            self._cache.clear()
        logger.info("Smart cache cleared.")

    def get_stats(self) -> Dict[str, Any]:
        """Return cache statistics."""
        with self._lock:
            total = self._hits + self._misses
            hit_rate_pct = (100.0 * self._hits / total) if total > 0 else 0.0
            estimated_savings_usd = self._hits * COST_PER_SAVED_REQUEST

        return {
            "hits": self._hits,
            "misses": self._misses,
            "total_requests": total,
            "hit_rate_percent": round(hit_rate_pct, 2),
            "cache_size": len(self._cache),
            "max_entries": self._max_entries,
            "ttl_hours": self._ttl.total_seconds() / 3600,
            "estimated_savings_usd": round(estimated_savings_usd, 4),
        }

    def preload_from_faqs(self, faqs: List[Dict[str, Any]]) -> int:
        """
        Preload cache with FAQ question -> answer.
        faqs: list of dicts with 'question' and 'answer' keys.
        Returns number of entries added.
        """
        count = 0
        for faq in faqs or []:
            q = faq.get("question")
            a = faq.get("answer")
            if q and a:
                self.set(q, a)
                count += 1
        if count:
            logger.info("Smart cache preloaded with %d FAQ entries.", count)
        return count


# Global singleton
_smart_cache: Optional[SmartCache] = None


def get_smart_cache() -> SmartCache:
    """Get or create global SmartCache instance."""
    global _smart_cache
    if _smart_cache is None:
        _smart_cache = SmartCache(ttl_hours=DEFAULT_TTL_HOURS, max_entries=50_000)
    return _smart_cache
