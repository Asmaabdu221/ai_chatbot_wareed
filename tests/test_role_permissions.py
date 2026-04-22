"""
Tests for the internal RBAC layer.

Coverage:
  1.  admin can access leads list
  2.  supervisor can access leads list
  3.  staff can access leads list
  4.  User with NULL role is denied (403)
  5.  Invalid / no credential → API key fallback path
  6.  API key fallback still works (X-Internal-Api-Key header)
  7.  API key fallback works with dev mode (empty key configured)
  8.  Only allowed roles can close leads (close_lead route)
  9.  SSE dependency accepts ?api_key= query param
  10. SSE dependency accepts ?token= JWT query param
  11. SSE dependency denies no-credential + no-key
  12. require_internal_access raises 403 for authenticated user without role
  13. can_view_leads / can_close_leads permission helpers
  14. UserRole enum values
  15. User.role column defaults to None on creation
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from types import SimpleNamespace

from app.core.permissions import (
    INTERNAL_ROLES,
    can_close_leads,
    can_view_leads,
    require_internal_access,
    require_internal_access_sse,
)
from app.db.models import UserRole


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(role=None, active=True):
    """Return a minimal User-like namespace (no DB, no ORM init needed)."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex[:8]}@test.internal",
        is_active=active,
        role=role,
    )


def _bearer_creds(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def _call_require(
    token: str | None = None,
    api_key_header: str = "",
    db_user: User | None = None,
    settings_key: str = "",
):
    """
    Call require_internal_access directly, bypassing FastAPI dependency injection.
    Mocks the DB and settings as needed.
    """
    creds = _bearer_creds(token) if token else None

    with patch("app.core.permissions.settings") as mock_settings, \
         patch("app.core.permissions._resolve_bearer") as mock_resolve:
        mock_settings.INTERNAL_LEADS_API_KEY = settings_key
        mock_resolve.return_value = db_user

        mock_db = MagicMock()
        return require_internal_access(
            credentials=creds,
            x_internal_api_key=api_key_header,
            db=mock_db,
        )


def _call_require_sse(
    jwt_token: str | None = None,
    query_token: str = "",
    api_key_query: str = "",
    api_key_header: str = "",
    db_user: User | None = None,
    settings_key: str = "",
):
    creds = _bearer_creds(jwt_token) if jwt_token else None
    with patch("app.core.permissions.settings") as mock_settings, \
         patch("app.core.permissions._resolve_bearer") as mock_resolve:
        mock_settings.INTERNAL_LEADS_API_KEY = settings_key
        mock_resolve.return_value = db_user
        mock_db = MagicMock()
        return require_internal_access_sse(
            credentials=creds,
            token=query_token,
            api_key=api_key_query,
            x_internal_api_key=api_key_header,
            db=mock_db,
        )


# ---------------------------------------------------------------------------
# 1-3. All internal roles can access leads
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("role", [UserRole.ADMIN, UserRole.SUPERVISOR, UserRole.STAFF])
def test_internal_roles_granted(role):
    user = _make_user(role=role.value)
    result = _call_require(token="valid_token", db_user=user)
    assert result is user


# ---------------------------------------------------------------------------
# 4. User with NULL role is denied
# ---------------------------------------------------------------------------

def test_null_role_denied():
    user = _make_user(role=None)
    with pytest.raises(HTTPException) as exc_info:
        _call_require(token="valid_token", db_user=user)
    assert exc_info.value.status_code == 403


def test_unknown_role_denied():
    user = _make_user(role="viewer")  # not a valid internal role
    with pytest.raises(HTTPException) as exc_info:
        _call_require(token="valid_token", db_user=user)
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# 5. No credential + no API key → 403
# ---------------------------------------------------------------------------

def test_no_credential_no_key_denied():
    with pytest.raises(HTTPException) as exc_info:
        _call_require(token=None, api_key_header="", settings_key="secret123")
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# 6. API key fallback works
# ---------------------------------------------------------------------------

def test_api_key_header_accepted():
    result = _call_require(token=None, api_key_header="correct_key", settings_key="correct_key")
    assert result is None  # no User object on API-key path


def test_api_key_header_wrong_key_denied():
    with pytest.raises(HTTPException) as exc_info:
        _call_require(token=None, api_key_header="wrong_key", settings_key="correct_key")
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# 7. Dev mode: empty key → always accepted
# ---------------------------------------------------------------------------

def test_dev_mode_no_key_configured():
    result = _call_require(token=None, api_key_header="", settings_key="")
    assert result is None  # dev mode allows any request


def test_dev_mode_any_value_accepted():
    result = _call_require(token=None, api_key_header="random_garbage", settings_key="")
    assert result is None


# ---------------------------------------------------------------------------
# 8. Only allowed roles can close (close_lead route uses same dependency)
# ---------------------------------------------------------------------------

def test_admin_can_close():
    user = _make_user(role="admin")
    assert can_close_leads(user) is True


def test_supervisor_can_close():
    user = _make_user(role="supervisor")
    assert can_close_leads(user) is True


def test_staff_can_close():
    user = _make_user(role="staff")
    assert can_close_leads(user) is True


def test_no_role_cannot_close():
    user = _make_user(role=None)
    assert can_close_leads(user) is False


def test_api_key_user_can_close():
    assert can_close_leads(None) is True  # API-key path: user=None


# ---------------------------------------------------------------------------
# 9. SSE: ?api_key= query param
# ---------------------------------------------------------------------------

def test_sse_api_key_query_param():
    result = _call_require_sse(api_key_query="mykey", settings_key="mykey")
    assert result is None


def test_sse_api_key_wrong_denied():
    with pytest.raises(HTTPException) as exc_info:
        _call_require_sse(api_key_query="wrong", settings_key="mykey")
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# 10. SSE: ?token= JWT query param
# ---------------------------------------------------------------------------

def test_sse_token_query_param_with_valid_role():
    user = _make_user(role="admin")
    result = _call_require_sse(query_token="jwt_value", db_user=user)
    assert result is user


def test_sse_token_query_param_no_role_denied():
    user = _make_user(role=None)
    with pytest.raises(HTTPException) as exc_info:
        _call_require_sse(query_token="jwt_value", db_user=user)
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# 11. SSE: no credential + no key → 403
# ---------------------------------------------------------------------------

def test_sse_no_credential_denied():
    with pytest.raises(HTTPException) as exc_info:
        _call_require_sse(settings_key="required_key")
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# 12. Authenticated user without role gets explicit 403 (not fallback to API key)
# ---------------------------------------------------------------------------

def test_authenticated_no_role_does_not_fallback_to_api_key():
    """
    If a valid JWT is sent but the user has no internal role,
    we raise 403 immediately without checking the API key.
    This prevents privilege escalation via API key + valid JWT.
    """
    user = _make_user(role=None)
    with pytest.raises(HTTPException) as exc_info:
        _call_require(token="valid_jwt", api_key_header="correct_key", db_user=user, settings_key="correct_key")
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# 13. Permission helpers
# ---------------------------------------------------------------------------

def test_can_view_leads_all_roles():
    for role in ("admin", "supervisor", "staff"):
        assert can_view_leads(_make_user(role=role)) is True


def test_can_view_leads_null_role():
    assert can_view_leads(_make_user(role=None)) is False


def test_can_view_leads_api_key_path():
    assert can_view_leads(None) is True


def test_can_close_leads_all_roles():
    for role in ("admin", "supervisor", "staff"):
        assert can_close_leads(_make_user(role=role)) is True


# ---------------------------------------------------------------------------
# 14. UserRole enum values
# ---------------------------------------------------------------------------

def test_user_role_enum_values():
    assert UserRole.ADMIN.value == "admin"
    assert UserRole.SUPERVISOR.value == "supervisor"
    assert UserRole.STAFF.value == "staff"
    assert set(r.value for r in UserRole) == INTERNAL_ROLES


# ---------------------------------------------------------------------------
# 15. User.role column defaults to None
# ---------------------------------------------------------------------------

def test_user_role_defaults_to_none(db):
    """New users created without a role have role=None."""
    from app.core.security import hash_password
    from app.db.models import User

    user = User(
        email=f"{uuid.uuid4().hex[:8]}@test.internal",
        password_hash=hash_password("TestPassword123"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    assert user.role is None
