"""
JWT and password security (platform-agnostic: Web + Mobile)
Uses Bearer token only; no cookies or server-side sessions.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Optional
from uuid import UUID

import jwt
from passlib.context import CryptContext

from app.core.config import settings

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Token type claims
TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_REFRESH = "refresh"


def hash_password(plain_password: str) -> str:
    """Hash a plain password for storage."""
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a hash."""
    return pwd_context.verify(plain_password, hashed_password)


def _make_payload(
    user_id: UUID,
    token_type: str,
    expire_delta: timedelta,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    return {
        "sub": str(user_id),
        "type": token_type,
        "iat": now,
        "exp": now + expire_delta,
    }


def create_access_token(user_id: UUID) -> str:
    """Create a short-lived access token (Bearer)."""
    payload = _make_payload(
        user_id,
        TOKEN_TYPE_ACCESS,
        timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return jwt.encode(
        payload,
        settings.SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def create_refresh_token(user_id: UUID) -> str:
    """Create a long-lived refresh token for obtaining new access tokens."""
    payload = _make_payload(
        user_id,
        TOKEN_TYPE_REFRESH,
        timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )
    return jwt.encode(
        payload,
        settings.SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def decode_token(token: str) -> Optional[dict[str, Any]]:
    """
    Decode and validate a JWT. Returns payload dict or None if invalid/expired.
    """
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        return payload
    except jwt.ExpiredSignatureError:
        logger.debug("Token expired")
        return None
    except jwt.InvalidTokenError:
        logger.debug("Invalid token")
        return None


def decode_access_token(token: str) -> Optional[str]:
    """
    Decode an access token and return user_id (sub) if valid and type is access.
    """
    payload = decode_token(token)
    if not payload or payload.get("type") != TOKEN_TYPE_ACCESS:
        return None
    return payload.get("sub")


def decode_refresh_token(token: str) -> Optional[str]:
    """
    Decode a refresh token and return user_id (sub) if valid and type is refresh.
    """
    payload = decode_token(token)
    if not payload or payload.get("type") != TOKEN_TYPE_REFRESH:
        return None
    return payload.get("sub")
