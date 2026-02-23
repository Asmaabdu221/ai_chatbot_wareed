"""
Authentication API — JWT Bearer only (platform-agnostic: Web + Mobile).
No cookies, no server-side sessions. Same flow for all clients.
"""

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    hash_password,
    verify_password,
)
from app.db import get_db
from app.db.models import User

logger = logging.getLogger(__name__)

router = APIRouter()


# ----- Request/Response models -----


class RegisterRequest(BaseModel):
    """Registration body: email + password (same for Web and Mobile)."""
    email: EmailStr = Field(..., description="User email")
    password: str = Field(..., min_length=8, max_length=128, description="Password (min 8 chars)")


class LoginRequest(BaseModel):
    """Login body: email + password."""
    email: EmailStr = Field(..., description="User email")
    password: str = Field(..., description="Password")


class RefreshRequest(BaseModel):
    """Refresh token body (client stores refresh_token in secure storage or memory)."""
    refresh_token: str = Field(..., description="Refresh token from login/register")


class TokenResponse(BaseModel):
    """Tokens returned on login/register/refresh. Client stores and sends Bearer access_token."""
    access_token: str = Field(..., description="JWT access token — send as Authorization: Bearer <token>")
    refresh_token: str = Field(..., description="Refresh token to obtain new access_token")
    token_type: str = Field(default="bearer", description="Token type")
    expires_in: int = Field(..., description="Access token TTL in seconds")


class UserMeResponse(BaseModel):
    """Current user info (from /auth/me)."""
    id: UUID
    email: Optional[str] = None
    display_name: Optional[str] = None
    username: Optional[str] = None
    avatar_url: Optional[str] = None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class ProfileUpdateRequest(BaseModel):
    """Profile update body."""
    display_name: Optional[str] = Field(None, max_length=255)
    username: Optional[str] = Field(None, min_length=2, max_length=64)


def _db_required(db: Optional[Session]) -> None:
    if db is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="قاعدة البيانات غير مفعّلة. التسجيل والدخول غير متاحين.",
        )


def _tokens_for_user(user_id: UUID) -> TokenResponse:
    access = create_access_token(user_id)
    refresh = create_refresh_token(user_id)
    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


# ----- Endpoints -----


@router.post(
    "/register",
    response_model=TokenResponse,
    summary="Register (Web / Mobile)",
    description="Create account. Returns access_token + refresh_token. Store and send: Authorization: Bearer <access_token>.",
)
async def register(
    body: RegisterRequest,
    db: Optional[Session] = Depends(get_db),
    request: Request = None,
) -> TokenResponse:
    _db_required(db)
    if request is not None:
        logger.info("Auth request %s %s", request.method, request.url.path)
    logger.info("User registration attempt")
    email = body.email.lower()

    def _register_sync() -> UUID:
        existing = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if existing:
            logger.warning("Registration failed: email already registered")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="البريد الإلكتروني مسجّل مسبقاً.",
            )
        try:
            hashed_password = hash_password(body.password)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(e),
            )
        except Exception:
            password_bytes = len((body.password or "").encode("utf-8", errors="ignore"))
            logger.warning("Registration failed: password hashing error (password_bytes=%s)", password_bytes)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="تعذر معالجة كلمة المرور. تأكد من أنها نص صالح وبطول مناسب.",
            )
        user = User(
            email=email,
            password_hash=hashed_password,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        logger.info("User registration successful (user_id=%s)", str(user.id))
        return user.id

    user_id = await run_in_threadpool(_register_sync)
    return _tokens_for_user(user_id)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login (Web / Mobile)",
    description="Login with email + password. Returns access_token + refresh_token. Same flow for all platforms.",
)
async def login(
    body: LoginRequest,
    db: Optional[Session] = Depends(get_db),
    request: Request = None,
) -> TokenResponse:
    _db_required(db)
    if request is not None:
        logger.info("Auth request %s %s", request.method, request.url.path)
    email = body.email.lower()

    def _login_sync() -> UUID:
        user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        try:
            is_valid_password = bool(user and user.password_hash and verify_password(body.password, user.password_hash))
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(e),
            )
        except Exception:
            password_bytes = len((body.password or "").encode("utf-8", errors="ignore"))
            logger.warning("Login failed: password verification error (password_bytes=%s)", password_bytes)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="تعذر التحقق من كلمة المرور. تأكد من أنها نص صالح وبطول مناسب.",
            )
        if not is_valid_password:
            logger.warning("Login failed: invalid credentials")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="البريد الإلكتروني أو كلمة المرور غير صحيحة.",
            )
        if not user.is_active:
            logger.warning("Login failed: account disabled")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="الحساب غير مفعّل.",
            )
        from datetime import timezone
        user.last_active_at = datetime.now(timezone.utc)
        db.commit()
        logger.info("User login successful (user_id=%s)", str(user.id))
        return user.id

    user_id = await run_in_threadpool(_login_sync)
    return _tokens_for_user(user_id)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh access token (Web / Mobile)",
    description="Get new access_token using refresh_token. No re-login needed when access expires.",
)
def refresh(
    body: RefreshRequest,
    db: Optional[Session] = Depends(get_db),
) -> TokenResponse:
    _db_required(db)
    user_id_str = decode_refresh_token(body.refresh_token)
    if not user_id_str:
        logger.warning("Token refresh failed: invalid or expired token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="توكن التحديث غير صالح أو منتهي الصلاحية.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        user_id = UUID(user_id_str)
    except ValueError:
        logger.warning("Token refresh failed: invalid token format")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="توكن غير صالح.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = db.get(User, user_id)
    if not user or not user.is_active:
        logger.warning("Token refresh failed: user not found or inactive")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="المستخدم غير موجود أو غير مفعّل.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    logger.info("Token refresh successful (user_id=%s)", str(user_id))
    return _tokens_for_user(user.id)


@router.get(
    "/me",
    response_model=UserMeResponse,
    summary="Current user (Web / Mobile)",
    description="Requires Authorization: Bearer <access_token>. Returns current user info.",
)
def me(
    current_user: User = Depends(get_current_user),
) -> UserMeResponse:
    return UserMeResponse(
        id=current_user.id,
        email=current_user.email,
        display_name=current_user.display_name,
        username=current_user.username,
        avatar_url=current_user.avatar_url,
        is_active=current_user.is_active,
        created_at=current_user.created_at,
    )


def _get_avatars_dir() -> Path:
    """Return avatars upload directory, create if needed."""
    root = Path(__file__).resolve().parents[2]
    avatars_dir = root / "media" / "avatars"
    avatars_dir.mkdir(parents=True, exist_ok=True)
    return avatars_dir


@router.patch(
    "/profile",
    response_model=UserMeResponse,
    summary="Update profile",
    description="Update display_name and/or username. Requires Bearer token.",
)
async def update_profile(
    body: ProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Optional[Session] = Depends(get_db),
) -> UserMeResponse:
    _db_required(db)

    def _update_sync() -> User:
        if body.display_name is not None:
            current_user.display_name = body.display_name.strip() or None
        if body.username is not None:
            username = body.username.strip().lower()
            if username:
                existing = db.execute(select(User).where(User.username == username, User.id != current_user.id)).scalar_one_or_none()
                if existing:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="اسم المستخدم مستخدم من قبل.",
                    )
                current_user.username = username
            else:
                current_user.username = None
        db.commit()
        db.refresh(current_user)
        return current_user

    try:
        updated = await run_in_threadpool(_update_sync)
    except HTTPException:
        raise
    return UserMeResponse(
        id=updated.id,
        email=updated.email,
        display_name=updated.display_name,
        username=updated.username,
        avatar_url=updated.avatar_url,
        is_active=updated.is_active,
        created_at=updated.created_at,
    )


ALLOWED_AVATAR_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}
ALLOWED_AVATAR_EXT = {".jpg", ".jpeg", ".png", ".webp"}


@router.post(
    "/profile/avatar",
    response_model=dict,
    summary="Upload profile avatar",
    description="Upload profile image (JPEG, PNG, WebP). Returns avatar_url.",
)
async def upload_avatar(
    file: UploadFile = File(..., description="Profile image (JPEG, PNG, WebP)"),
    current_user: User = Depends(get_current_user),
    db: Optional[Session] = Depends(get_db),
) -> dict:
    _db_required(db)
    content_type = (file.content_type or "").lower()
    if content_type not in ALLOWED_AVATAR_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="صيغة غير مدعومة. استخدم JPEG أو PNG أو WebP.",
        )
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_AVATAR_EXT:
        ext = ".jpg"
    try:
        data = await file.read()
    except Exception as e:
        logger.error("Failed to read avatar file: %s", e)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="فشل قراءة الملف.")
    if len(data) > 5 * 1024 * 1024:  # 5MB
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="حجم الصورة كبير جداً (الحد 5 ميجابايت).")
    avatars_dir = _get_avatars_dir()
    filename = f"{current_user.id}_{uuid4().hex}{ext}"
    filepath = avatars_dir / filename
    try:
        with open(filepath, "wb") as f:
            f.write(data)
    except Exception as e:
        logger.error("Failed to save avatar: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="فشل حفظ الصورة.")
    file_exists = os.path.exists(filepath)
    avatar_url = f"/media/avatars/{filename}"
    current_user.avatar_url = avatar_url
    db.commit()
    db.refresh(current_user)
    response_payload = {"avatar_url": avatar_url}
    logger.info(
        "Avatar upload saved for user_id=%s abs_path=%s bytes=%s file_exists=%s avatar_url=%s response=%s",
        str(current_user.id),
        str(filepath.resolve()),
        len(data),
        file_exists,
        avatar_url,
        response_payload,
    )
    return response_payload
