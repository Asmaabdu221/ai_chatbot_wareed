"""
Knowledge Context Cache
========================
Caches RAG context (get_knowledge_context results) to avoid recomputing
semantic/fuzzy search and formatting for the same or normalized query.
"""

import hashlib
import re
import threading
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

DEFAULT_TTL_HOURS = 1.0
DEFAULT_MAX_ENTRIES = 10_000
STATE_TTL_MINUTES = 15
STATE_KEY_PREFIXES = ("flow_state:", "branch_selection:", "package_selection:")


def _normalize_message(text: str) -> str:
    if not text or not isinstance(text, str):
        return ""
    t = text.strip().lower()
    t = re.sub(r"\s+", " ", t)
    return t


def make_context_cache_key(
    user_message: str, max_tests: int, max_faqs: int, include_prices: bool
) -> str:
    """Build cache key from get_knowledge_context arguments."""
    raw = f"{_normalize_message(user_message)}|{max_tests}|{max_faqs}|{include_prices}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ContextCache:
    """
    In-memory cache for knowledge context strings.
    Key = hash(normalized message + params), value = context text.
    """

    def __init__(self, ttl_hours: float = DEFAULT_TTL_HOURS, max_entries: int = DEFAULT_MAX_ENTRIES):
        self._store: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._ttl = timedelta(hours=ttl_hours)
        self._max_entries = max(500, max_entries)
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            if key not in self._store:
                self._misses += 1
                return None
            entry = self._store[key]
            if datetime.utcnow() >= entry["expires_at"]:
                del self._store[key]
                self._misses += 1
                return None
            self._hits += 1
            return entry["value"]

    def set(self, key: str, value: str) -> None:
        if not value:
            return
        now = datetime.utcnow()
        ttl = self._ttl
        if isinstance(key, str) and key.startswith(STATE_KEY_PREFIXES):
            ttl = timedelta(minutes=STATE_TTL_MINUTES)
        with self._lock:
            if len(self._store) >= self._max_entries and key not in self._store:
                self._evict_one()
            self._store[key] = {
                "value": value,
                "expires_at": now + ttl,
            }

    def _evict_one(self) -> None:
        now = datetime.utcnow()
        for k, v in list(self._store.items()):
            if now >= v["expires_at"]:
                del self._store[k]
                return
        if self._store:
            oldest = min(self._store.keys(), key=lambda k: self._store[k]["expires_at"])
            del self._store[oldest]

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            total = self._hits + self._misses
            hit_rate = (100.0 * self._hits / total) if total > 0 else 0.0
        return {
            "hits": self._hits,
            "misses": self._misses,
            "total_requests": total,
            "hit_rate_percent": round(hit_rate, 2),
            "cache_size": len(self._store),
            "max_entries": self._max_entries,
            "ttl_hours": self._ttl.total_seconds() / 3600,
        }

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
        logger.info("Context cache cleared.")


_context_cache: Optional[ContextCache] = None


def get_context_cache() -> ContextCache:
    global _context_cache
    if _context_cache is None:
        _context_cache = ContextCache(ttl_hours=DEFAULT_TTL_HOURS, max_entries=DEFAULT_MAX_ENTRIES)
    return _context_cache
