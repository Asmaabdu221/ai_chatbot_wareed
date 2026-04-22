"""
Internal RBAC — role-based access control for staff operations.

Two access paths (both remain supported):

  1. JWT Bearer + internal role  (primary, long-term path)
     ‣ User must have role ∈ {admin, supervisor, staff}
     ‣ Role is stored on User.role (String column, NULL = regular chat user)

  2. X-Internal-Api-Key / ?api_key= query param  (compatibility / service-to-service)
     ‣ Matches settings.INTERNAL_LEADS_API_KEY
     ‣ Dev mode: if that setting is empty → always accepted
     ‣ Used by SSE stream (EventSource cannot send custom headers)
     ‣ Transitional: keep until all callers migrate to role-based auth

SSE variant also accepts ?token=<JWT> so EventSource clients can authenticate
without a custom header.

Role permissions (current — all three roles are identical intentionally so the
architecture is ready for future differentiation):

  admin       → view leads, close leads, dashboard
  supervisor  → view leads, close leads, dashboard
  staff       → view leads, close leads, dashboard
"""

from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Query, status
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
    """Return True if the provided API key is acceptable."""
    expected = (settings.INTERNAL_LEADS_API_KEY or "").strip()
    if not expected:
        return True  # dev mode: no key configured → open
    return provided == expected


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
    token: str = Query(default="", description="JWT Bearer token (for EventSource that cannot send headers)"),
    api_key: str = Query(default=""),
    x_internal_api_key: str = Header(default=""),
    db: Optional[Session] = Depends(get_db),
) -> Optional[User]:
    """
    SSE-compatible variant of require_internal_access.

    EventSource (browser native API) cannot set custom headers, so we also
    accept credentials via query params:
      • ?token=<JWT>    — JWT Bearer alternative
      • ?api_key=<key>  — API key alternative (existing behaviour)
    """
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    # --- Path 1: JWT Bearer (header takes priority, then ?token= param) ---
    jwt_token = (credentials.credentials if credentials else "") or token
    if jwt_token:
        user = _resolve_bearer(jwt_token, db)
        if user is not None:
            if user.role in INTERNAL_ROLES:
                return user
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="حسابك لا يمتلك صلاحية الوصول الداخلي.",
            )

    # --- Path 2: API key (header takes priority, then ?api_key= param) ---
    key = x_internal_api_key or api_key
    if _api_key_ok(key):
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
