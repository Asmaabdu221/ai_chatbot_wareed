"""
FastAPI dependencies for authentication (platform-agnostic).
Expects Authorization: Bearer <token>; no cookies or sessions.
"""

import logging
from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db import get_db
from app.db.models import User

logger = logging.getLogger(__name__)

# Bearer scheme only; clients (Web/Mobile) send: Authorization: Bearer <token>
security = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Optional[Session] = Depends(get_db),
) -> User:
    """
    Require valid JWT Bearer token; return the authenticated user.
    Use for endpoints that require login (e.g. /auth/me, protected routes).
    """
    if db is None:
        logger.error("Authorization failed: database not available")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="قاعدة البيانات غير مفعّلة. المصادقة غير متاحة.",
        )
    if not credentials or credentials.credentials is None:
        logger.warning("Authorization failed: no token provided")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="مطلوب توكن مصادقة. أرسل الرأس: Authorization: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = credentials.credentials
    user_id_str = decode_access_token(token)
    if not user_id_str:
        logger.warning("Authorization failed: invalid or expired token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="توكن غير صالح أو منتهي الصلاحية",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        user_id = UUID(user_id_str)
    except ValueError:
        logger.warning("Authorization failed: invalid token format")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="توكن غير صالح",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = db.get(User, user_id)
    if not user:
        logger.warning("Authorization failed: user not found (user_id=%s)", user_id_str)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="المستخدم غير موجود",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        logger.warning("Authorization failed: account disabled (user_id=%s)", user_id_str)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="الحساب غير مفعّل",
        )
    return user


def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Optional[Session] = Depends(get_db),
) -> Optional[User]:
    """
    Optional auth: if valid Bearer token is sent, return the user; otherwise None.
    Use for endpoints that work both authenticated and anonymous (e.g. chat).
    """
    if db is None or not credentials or not credentials.credentials:
        return None
    token = credentials.credentials
    user_id_str = decode_access_token(token)
    if not user_id_str:
        return None
    try:
        user_id = UUID(user_id_str)
    except ValueError:
        return None
    user = db.get(User, user_id)
    if not user or not user.is_active:
        return None
    return user
