"""
Rate Limiter Service
====================
Sliding-window rate limiting per client (IP or user_id) to prevent abuse.
"""

import logging
import threading
import time
from collections import defaultdict
from typing import DefaultDict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Default: 10 requests per 60 seconds per client
DEFAULT_MAX_REQUESTS = 10
DEFAULT_WINDOW_SECONDS = 60


class RateLimiter:
    """
    Sliding-window rate limiter. Thread-safe, in-memory.
    """

    def __init__(
        self,
        max_requests: int = DEFAULT_MAX_REQUESTS,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
    ):
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._timestamps: DefaultDict[str, List[float]] = defaultdict(list)
        self._lock = threading.RLock()

    def _clean_old(self, key: str, now: float) -> None:
        """Remove timestamps outside the sliding window."""
        cutoff = now - self._window_seconds
        self._timestamps[key] = [t for t in self._timestamps[key] if t > cutoff]

    def is_allowed(self, client_id: str) -> Tuple[bool, Optional[int]]:
        """
        Returns (allowed, retry_after_seconds).
        If allowed is False, retry_after_seconds is the suggested wait time.
        """
        if not client_id:
            return True, None
        now = time.monotonic()
        with self._lock:
            self._clean_old(client_id, now)
            timestamps = self._timestamps[client_id]
            if len(timestamps) >= self._max_requests:
                oldest = min(timestamps)
                retry_after = int(self._window_seconds - (now - oldest))
                retry_after = max(1, min(retry_after, int(self._window_seconds)))
                logger.warning(
                    "Rate limit exceeded for client_id=%s (count=%s)",
                    client_id[:20],
                    len(timestamps),
                )
                return False, retry_after
            timestamps.append(now)
            return True, None

    def get_stats(self) -> dict:
        """Return basic stats: number of tracked keys."""
        with self._lock:
            return {
                "tracked_clients": len(self._timestamps),
                "max_requests_per_window": self._max_requests,
                "window_seconds": self._window_seconds,
            }


_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    global _limiter
    if _limiter is None:
        _limiter = RateLimiter(
            max_requests=DEFAULT_MAX_REQUESTS,
            window_seconds=DEFAULT_WINDOW_SECONDS,
        )
    return _limiter
