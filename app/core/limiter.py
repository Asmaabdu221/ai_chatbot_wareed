"""
Shared application rate limiter (slowapi).

A single Limiter instance is created here so it can be:
  • registered on the FastAPI app (app.state.limiter) in app/main.py, and
  • imported by routers (e.g. app/api/auth.py) to decorate specific endpoints.

Keying is per client IP (get_remote_address). Storage is in-process memory by
default; for multi-worker / multi-instance deployments set a Redis backend via
RATE_LIMIT_STORAGE_URI (or REDIS_URL) so limits are shared across workers.
"""

import logging
import os

from slowapi import Limiter
from slowapi.util import get_remote_address

logger = logging.getLogger(__name__)

# Prefer an explicit rate-limit store, then the app's Redis, else in-memory.
_storage_uri = (
    os.getenv("RATE_LIMIT_STORAGE_URI")
    or os.getenv("REDIS_URL")
    or "memory://"
)

try:
    limiter = Limiter(key_func=get_remote_address, storage_uri=_storage_uri)
    if _storage_uri != "memory://":
        logger.info("Rate limiter using shared storage backend")
except Exception as exc:  # never let limiter init break app import
    logger.warning(
        "Rate limiter storage init failed (%s); falling back to in-memory",
        exc.__class__.__name__,
    )
    limiter = Limiter(key_func=get_remote_address, storage_uri="memory://")
