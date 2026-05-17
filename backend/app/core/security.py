"""JWT issuance, password hashing, and the FastAPI auth dependency.

Every token carries a ``jti`` (random UUID hex) so it can be revoked via
Redis blacklist on logout or refresh-rotation. See
``app.services.token_blacklist_service``.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import get_db
from app.models.user import User
from app.services.token_blacklist_service import is_revoked

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


# ── Password hashing (native bcrypt to avoid the passlib 72-byte bug) ───
def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        if isinstance(hashed_password, str):
            hashed_password = hashed_password.encode("utf-8")
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password)
    except (ValueError, TypeError):
        # Malformed hash or non-string password → not a match. Everything
        # else propagates so we don't silently swallow library bugs.
        return False


def get_password_hash(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


# ── JWT issuance ────────────────────────────────────────────────────────
def _build_token(data: dict, expires_delta: timedelta, token_type: str) -> str:
    """Encode a JWT with a fresh ``jti`` and a ``type`` claim."""
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    expire = now + expires_delta
    to_encode.update({
        "exp": expire,
        "iat": now,
        "type": token_type,
        "jti": uuid.uuid4().hex,
    })
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    return _build_token(
        data,
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        "access",
    )


def create_refresh_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    return _build_token(
        data,
        expires_delta or timedelta(minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES),
        "refresh",
    )


def decode_token(token: str) -> dict:
    """Decode + validate a JWT. Raises ``JWTError`` on invalid/expired tokens.

    Blacklist check is NOT done here — call sites that care (auth dependency,
    refresh endpoint) explicitly call ``is_revoked`` on the returned ``jti``.
    Keeping decode pure makes it usable in sync test code.
    """
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])


# ── FastAPI auth dependency ─────────────────────────────────────────────
async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token)
    except JWTError:
        raise credentials_exception

    username: str = payload.get("sub")
    token_type: str = payload.get("type", "access")
    jti: str | None = payload.get("jti")
    if not username or token_type != "access" or not jti:
        # Reject access tokens issued before the jti rollout — they cannot be
        # revoked via the blacklist and would create a permanent un-loggable
        # session. Users with a still-valid pre-rollout token will be force-
        # logged-out once (their 30-min access expires or this check fires);
        # the frontend's 401 → refresh path then issues a fresh jti-bearing
        # pair, so the disruption is bounded.
        raise credentials_exception

    if await is_revoked(jti):
        raise credentials_exception

    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise credentials_exception
    return user
