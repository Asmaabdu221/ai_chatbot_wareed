"""
Internal RBAC — role-based access control for staff operations.

Two access paths (both remain supported):

  1. JWT Bearer + internal role  (primary, long-term path)
     ‣ User must have role ∈ {admin, supervisor, staff}
     ‣ Role is stored on User.role (String column, NULL = regular chat user)

  2. X-Internal-Api-Key header  (compatibility / service-to-service)
     ‣ Matches settings.INTERNAL_LEADS_API_KEY
     ‣ Dev mode: if that setting is empty → accepted only in dev mode (DEBUG=True); otherwise denied
     ‣ Used by the SSE stream (sent as a header by a fetch-based client)
     ‣ Transitional: keep until all callers migrate to role-based auth

SSE clients authenticate via headers only (Authorization or X-Internal-Api-Key);
query-param credentials are not accepted.

Role permissions (current — all three roles are identical intentionally so the
architecture is ready for future differentiation):

  admin       → view leads, close leads, dashboard
  supervisor  → view leads, close leads, dashboard
  staff       → view leads, close leads, dashboard
"""

from __future__ import annotations

import logging
import secrets
from typing import Optional
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import get_db
from app.db.models import User, UserRole

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)

# All values that grant internal access
INTERNAL_ROLES: frozenset[str] = frozenset(r.value for r in UserRole)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _resolve_bearer(token: str, db: Session) -> Optional[User]:
    """Decode JWT access token and return the active User, or None if invalid."""
    from app.core.security import decode_access_token

    user_id_str = decode_access_token(token)
    if not user_id_str:
        return None
    try:
        uid = UUID(user_id_str)
    except ValueError:
        return None
    user = db.get(User, uid)
    if not user or not user.is_active:
        return None
    return user


def _api_key_ok(provided: str) -> bool:
    """Return True if the provided API key is acceptable.

    Fails CLOSED by default: when no INTERNAL_LEADS_API_KEY is configured,
    access is granted ONLY in explicit local/dev mode (settings.DEBUG=True).
    In production a missing key denies access instead of silently opening
    the internal endpoints (which expose customer/lead PII).

    Uses a constant-time comparison to avoid timing side-channels.
    """
    expected = (settings.INTERNAL_LEADS_API_KEY or "").strip()
    if not expected:
        if settings.DEBUG:
            logger.warning(
                "internal_access | api_key | DEV-ONLY open access: "
                "INTERNAL_LEADS_API_KEY is not set and DEBUG=True"
            )
            return True
        logger.error(
            "internal_access | denied | INTERNAL_LEADS_API_KEY is not configured; "
            "refusing access. Set the key (or enable DEBUG for local dev)."
        )
        return False
    return secrets.compare_digest((provided or "").strip(), expected)


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

def require_internal_access(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
    x_internal_api_key: str = Header(default=""),
    db: Optional[Session] = Depends(get_db),
) -> Optional[User]:
    """
    Dependency for non-SSE internal routes.

    Grants access (returns User or None) when:
      • Bearer token resolves to a User with an internal role, OR
      • X-Internal-Api-Key header matches settings.INTERNAL_LEADS_API_KEY

    Returns the authenticated User (JWT path) or None (API-key path).
    Raises HTTP 403 on all other cases.
    """
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    # --- Path 1: JWT Bearer ---
    if credentials and credentials.credentials:
        user = _resolve_bearer(credentials.credentials, db)
        if user is not None:
            if user.role in INTERNAL_ROLES:
                logger.debug("internal_access | jwt | user_id=%s role=%s", user.id, user.role)
                return user
            # Valid JWT but no internal role → explicit 403 (not a fall-through to API key)
            logger.warning(
                "internal_access | denied | user_id=%s has no internal role (role=%s)",
                user.id, user.role,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="حسابك لا يمتلك صلاحية الوصول الداخلي.",
            )

    # --- Path 2: API key ---
    if _api_key_ok(x_internal_api_key):
        logger.debug("internal_access | api_key | ok")
        return None  # access granted via API key; no user object

    logger.warning("internal_access | denied | no valid credential")
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="يتطلب الوصول الداخلي رمز Bearer مع دور داخلي، أو مفتاح API صالح.",
    )


def require_internal_access_sse(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
    x_internal_api_key: str = Header(default=""),
    db: Optional[Session] = Depends(get_db),
) -> Optional[User]:
    """
    SSE internal access — header-based credentials ONLY.

    Credentials must be supplied via request headers:
      • Authorization: Bearer <JWT>   — JWT with an internal role (preferred)
      • X-Internal-Api-Key: <key>     — service API key

    Query-param credentials (?token= / ?api_key=) are no longer accepted: they
    leak secrets into URLs, server/proxy access logs, and browser history.
    Browser EventSource cannot send headers, so SSE clients must use a fetch
    based reader that sets the Authorization (or X-Internal-Api-Key) header.
    """
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    # --- Path 1: JWT Bearer (header only) ---
    jwt_token = credentials.credentials if credentials else ""
    if jwt_token:
        user = _resolve_bearer(jwt_token, db)
        if user is not None:
            if user.role in INTERNAL_ROLES:
                return user
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="حسابك لا يمتلك صلاحية الوصول الداخلي.",
            )

    # --- Path 2: API key (header only) ---
    if _api_key_ok(x_internal_api_key):
        return None

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="يتطلب الوصول الداخلي رمز Bearer مع دور داخلي، أو مفتاح API صالح.",
    )


# ---------------------------------------------------------------------------
# Fine-grained permission helpers
# ---------------------------------------------------------------------------

def can_view_leads(user: Optional[User]) -> bool:
    """True for all internal roles and API-key-authenticated callers."""
    if user is None:
        return True  # API-key path
    return user.role in INTERNAL_ROLES


def can_close_leads(user: Optional[User]) -> bool:
    """True for all internal roles and API-key-authenticated callers."""
    if user is None:
        return True
    return user.role in INTERNAL_ROLES


def can_access_dashboard(user: Optional[User]) -> bool:
    return can_view_leads(user)
