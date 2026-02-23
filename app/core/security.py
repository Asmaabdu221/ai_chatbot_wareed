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
from passlib.exc import UnknownHashError

from app.core.config import settings

logger = logging.getLogger(__name__)

# New passwords are hashed with Argon2; existing bcrypt hashes remain verifiable.
pwd_context = CryptContext(
    schemes=["argon2", "bcrypt"],
    deprecated="auto",
)

MAX_PASSWORD_BYTES = 1024
BCRYPT_MAX_PASSWORD_BYTES = 72

# Token type claims
TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_REFRESH = "refresh"


def hash_password(plain_password: str) -> str:
    """Hash a plain password for storage."""
    _validate_password_for_hashing(plain_password)
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a hash."""
    if not hashed_password:
        return False

    password_bytes_len = _password_bytes_len(plain_password)
    scheme = pwd_context.identify(hashed_password)

    if scheme == "bcrypt" and password_bytes_len > BCRYPT_MAX_PASSWORD_BYTES:
        raise ValueError("كلمة المرور طويلة جدًا لهذا الحساب. يرجى إدخال كلمة مرور أقصر من 72 بايت.")

    if scheme is None:
        return False

    try:
        return pwd_context.verify(plain_password, hashed_password)
    except UnknownHashError:
        return False


def _password_bytes_len(password: str) -> int:
    if not isinstance(password, str):
        raise ValueError("صيغة كلمة المرور غير صالحة.")
    try:
        return len(password.encode("utf-8"))
    except UnicodeEncodeError:
        raise ValueError("كلمة المرور تحتوي على محارف غير صالحة.")


def _validate_password_for_hashing(password: str) -> None:
    password_bytes_len = _password_bytes_len(password)
    if password_bytes_len == 0:
        raise ValueError("كلمة المرور مطلوبة.")
    if password_bytes_len > MAX_PASSWORD_BYTES:
        raise ValueError("كلمة المرور طويلة جدًا. الحد الأقصى هو 1024 بايت.")


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
