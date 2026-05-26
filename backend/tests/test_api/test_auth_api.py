"""API tests for ``app.api.auth``.

These tests call the route handlers directly (not via TestClient) so we
avoid slowapi rate-limit decorators that require a Redis-backed Limiter,
and avoid bringing up the full FastAPI lifespan.

We build our own in-memory SQLite engine instead of using the shared
``db_session`` fixture in tests/conftest.py — that fixture references
``app.models.interview`` which no longer exists. (See report.)
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.api.auth import (
    EmailRequest,
    LogoutRequest,
    RefreshRequest,
    UserCreate,
    login_access_token,
    logout,
    refresh_access_token,
    register_user,
    send_verification_code,
)
from app.core.rate_limit import limiter as _rate_limiter
from app.core.security import create_access_token, create_refresh_token, decode_token
from app.db.database import Base
import app.models  # noqa: F401  — register all mappers before create_all
from app.models.user import User


@pytest.fixture(autouse=True)
def _disable_rate_limiter():
    """slowapi's @limiter.limit decorator counts hits with a real Limiter
    instance even when there's no app — flip it off for this module so the
    auth endpoints (5/min) don't 429 after the first handful of tests."""
    prev = _rate_limiter.enabled
    _rate_limiter.enabled = False
    yield
    _rate_limiter.enabled = prev


# ── Local engine / session (sidesteps broken conftest test_engine) ────────


@pytest.fixture
def db_session_local():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _fake_request(ip: str = "1.2.3.4") -> Request:
    """Build a real ``starlette.Request`` so the slowapi @limiter decorator
    accepts it. slowapi rejects MagicMock here with an explicit isinstance
    check, so we need the real type."""
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": [],
        "client": (ip, 0),
        "server": ("testserver", 80),
        "scheme": "http",
        "app": None,
    }
    return Request(scope)


def _make_user_create(
    username: str = "alice", password: str = "pw12345", email: str = "alice@example.com"
) -> UserCreate:
    return UserCreate(username=username, password=password, email=email, code="000000")


# ── send-code ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_code_register_existing_email_returns_fake_sent(db_session_local):
    """Account-enumeration guard: register-purpose for an existing email
    must return ``status=sent`` without actually issuing a code."""
    db_session_local.add(
        User(
            username="taken",
            email="taken@example.com",
            hashed_password="x",
            email_verified=True,
        )
    )
    db_session_local.commit()

    with patch("app.api.auth.request_code", new_callable=AsyncMock) as mock_req:
        result = await send_verification_code(
            request=_fake_request(),
            response=MagicMock(),
            payload=EmailRequest(email="taken@example.com", purpose="register"),
            db=db_session_local,
        )

    assert result["status"] == "sent"
    mock_req.assert_not_called()


@pytest.mark.asyncio
async def test_send_code_fresh_email_calls_request_code(db_session_local):
    with patch(
        "app.api.auth.request_code", new_callable=AsyncMock, return_value=600
    ) as mock_req:
        result = await send_verification_code(
            request=_fake_request(),
            response=MagicMock(),
            payload=EmailRequest(email="new@example.com", purpose="register"),
            db=db_session_local,
        )

    assert result == {"status": "sent", "expires_in": 600}
    mock_req.assert_awaited_once()


# ── register ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_success_creates_user(db_session_local):
    with patch("app.api.auth.assert_ip_not_locked", new_callable=AsyncMock), \
         patch("app.api.auth.verify_code", new_callable=AsyncMock), \
         patch("app.api.auth.reset_ip_failures", new_callable=AsyncMock):
        result = await register_user(
            request=_fake_request(),
            response=MagicMock(),
            user_in=_make_user_create(),
            db=db_session_local,
        )
    assert result["message"] == "User registered successfully"
    assert "user_id" in result
    saved = db_session_local.query(User).filter(User.username == "alice").first()
    assert saved is not None
    assert saved.email_verified is True


@pytest.mark.asyncio
async def test_register_duplicate_username_returns_generic_400(db_session_local):
    db_session_local.add(
        User(
            username="alice",
            email="other@example.com",
            hashed_password="x",
            email_verified=True,
        )
    )
    db_session_local.commit()

    with patch("app.api.auth.assert_ip_not_locked", new_callable=AsyncMock), \
         patch("app.api.auth.record_verify_failure_for_ip", new_callable=AsyncMock):
        with pytest.raises(HTTPException) as exc:
            await register_user(
                request=_fake_request(),
                response=MagicMock(),
                user_in=_make_user_create(),
                db=db_session_local,
            )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_register_bad_code_returns_generic_400(db_session_local):
    from app.services.auth.verification_code_service import CodeError

    with patch("app.api.auth.assert_ip_not_locked", new_callable=AsyncMock), \
         patch(
             "app.api.auth.verify_code",
             new_callable=AsyncMock,
             side_effect=CodeError("bad"),
         ), \
         patch("app.api.auth.record_verify_failure_for_ip", new_callable=AsyncMock):
        with pytest.raises(HTTPException) as exc:
            await register_user(
                request=_fake_request(),
                response=MagicMock(),
                user_in=_make_user_create(),
                db=db_session_local,
            )
    assert exc.value.status_code == 400


# ── login ─────────────────────────────────────────────────────────────────


def _register_sync(db, username="alice", password="pw12345") -> None:
    """Persist a user by bypassing the async register code path."""
    from app.core.security import get_password_hash

    db.add(
        User(
            username=username,
            email=f"{username}@example.com",
            hashed_password=get_password_hash(password),
            email_verified=True,
        )
    )
    db.commit()


def test_login_success_returns_token_pair(db_session_local):
    _register_sync(db_session_local, "alice", "pw12345")
    form = MagicMock(spec=OAuth2PasswordRequestForm)
    form.username = "alice"
    form.password = "pw12345"

    result = login_access_token(
        request=_fake_request(), response=MagicMock(),
        db=db_session_local, form_data=form,
    )

    assert result["token_type"] == "bearer"
    access_payload = decode_token(result["access_token"])
    refresh_payload = decode_token(result["refresh_token"])
    assert access_payload["sub"] == "alice"
    assert access_payload["type"] == "access"
    assert refresh_payload["type"] == "refresh"
    # JTI is required for revocation to be meaningful.
    assert access_payload.get("jti")
    assert refresh_payload.get("jti")


def test_login_wrong_password_returns_400(db_session_local):
    _register_sync(db_session_local, "alice", "right")
    form = MagicMock(spec=OAuth2PasswordRequestForm)
    form.username = "alice"
    form.password = "wrong"

    with pytest.raises(HTTPException) as exc:
        login_access_token(
            request=_fake_request(), response=MagicMock(),
            db=db_session_local, form_data=form,
        )
    assert exc.value.status_code == 400


def test_login_unknown_user_returns_400(db_session_local):
    form = MagicMock(spec=OAuth2PasswordRequestForm)
    form.username = "ghost"
    form.password = "irrelevant"
    with pytest.raises(HTTPException) as exc:
        login_access_token(
            request=_fake_request(), response=MagicMock(),
            db=db_session_local, form_data=form,
        )
    assert exc.value.status_code == 400


# ── refresh ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_refresh_rotates_tokens(db_session_local):
    _register_sync(db_session_local, "alice", "pw")
    refresh_token = create_refresh_token(data={"sub": "alice"})

    with patch("app.api.auth.is_revoked", new_callable=AsyncMock, return_value=False), \
         patch("app.api.auth.revoke", new_callable=AsyncMock) as mock_revoke:
        result = await refresh_access_token(
            request=_fake_request(),
            response=MagicMock(),
            body=RefreshRequest(refresh_token=refresh_token),
            db=db_session_local,
        )

    # Consumed refresh-token jti must be revoked (no replay).
    mock_revoke.assert_awaited_once()
    new_access = decode_token(result["access_token"])
    new_refresh = decode_token(result["refresh_token"])
    assert new_access["sub"] == "alice" and new_access["type"] == "access"
    assert new_refresh["sub"] == "alice" and new_refresh["type"] == "refresh"


@pytest.mark.asyncio
async def test_refresh_rejects_access_token(db_session_local):
    """An ``access`` token has the wrong ``type`` claim for /refresh."""
    _register_sync(db_session_local, "alice", "pw")
    access_token = create_access_token(data={"sub": "alice"})

    with patch("app.api.auth.is_revoked", new_callable=AsyncMock, return_value=False):
        with pytest.raises(HTTPException) as exc:
            await refresh_access_token(
                request=_fake_request(),
                response=MagicMock(),
                body=RefreshRequest(refresh_token=access_token),
                db=db_session_local,
            )
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_refresh_rejects_invalid_token(db_session_local):
    with pytest.raises(HTTPException) as exc:
        await refresh_access_token(
            request=_fake_request(),
            response=MagicMock(),
            body=RefreshRequest(refresh_token="not.a.jwt"),
            db=db_session_local,
        )
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_refresh_rejects_revoked_token(db_session_local):
    _register_sync(db_session_local, "alice", "pw")
    refresh_token = create_refresh_token(data={"sub": "alice"})

    with patch("app.api.auth.is_revoked", new_callable=AsyncMock, return_value=True):
        with pytest.raises(HTTPException) as exc:
            await refresh_access_token(
                request=_fake_request(),
                response=MagicMock(),
                body=RefreshRequest(refresh_token=refresh_token),
                db=db_session_local,
            )
    assert exc.value.status_code == 401


# ── logout ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_logout_revokes_both_tokens():
    access_token = create_access_token(data={"sub": "alice"})
    refresh_token = create_refresh_token(data={"sub": "alice"})

    with patch("app.api.auth.revoke", new_callable=AsyncMock) as mock_revoke:
        result = await logout(
            request=_fake_request(),
            response=MagicMock(),
            body=LogoutRequest(refresh_token=refresh_token),
            access_token=access_token,
        )

    assert result == {"status": "ok"}
    # Once for access, once for refresh.
    assert mock_revoke.await_count == 2


@pytest.mark.asyncio
async def test_logout_is_idempotent_with_garbage_access():
    """A bogus access token doesn't trip the endpoint — revoke is a no-op."""
    with patch("app.api.auth.revoke", new_callable=AsyncMock) as mock_revoke:
        result = await logout(
            request=_fake_request(),
            response=MagicMock(),
            body=None,
            access_token="not.a.jwt",
        )
    assert result == {"status": "ok"}
    mock_revoke.assert_not_called()
