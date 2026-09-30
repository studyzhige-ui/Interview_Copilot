"""JWT issuance, password hashing, and the FastAPI auth dependency.

Every token carries a ``jti`` (random UUID hex) so it can be revoked via
a durable SQL ledger on logout or refresh-rotation. See
``app.core.token_blacklist``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import jwt
from jwt.exceptions import PyJWTError as JWTError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.token_blacklist import is_revoked
from app.db.database import get_db
from app.models.user import User

# Public re-exports preserve the existing security API and tests.
from app.core.passwords import (  # noqa: F401
    get_password_hash,
    verify_password,
    verify_and_maybe_rehash,
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


# ── JWT issuance ────────────────────────────────────────────────────────
def _build_token(data: dict, expires_delta: timedelta, token_type: str) -> str:
    """Encode a JWT with a fresh ``jti`` and a ``type`` claim."""
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    expire = now + expires_delta
    to_encode.update(
        {
            "exp": expire,
            "iat": now,
            "type": token_type,
            "jti": uuid.uuid4().hex,
        }
    )
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


def token_claims_for(user: User) -> dict:
    """Identity claims embedded in every access/refresh token for ``user``.

    Single source of truth so login / refresh / any future issuer all agree:

      * ``sub``           — the stable ``users.id`` (string). This is the ONLY
        authoritative identity; ``username`` is mutable and never trusted for
        auth or business-row ownership.
      * ``token_version`` — snapshot of ``users.token_version`` at issuance.
        ``get_current_user`` / ``/auth/refresh`` reject the token if it no
        longer matches the row, which is how a password change invalidates
        every outstanding token at once.

    ``username`` is deliberately NOT included — keeping it out of the token
    removes any temptation to authorize against it.
    """
    return {"sub": str(user.id), "token_version": user.token_version}


# ── FastAPI auth dependency ─────────────────────────────────────────────
def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db, scope="function"),
) -> User:
    if settings.AUTH_PROVIDER == "supabase":
        from app.identity.application.supabase_auth import cloud_user
        from app.identity.application.local_unlock import local_user, LOCAL_ISSUER

        try:
            # Routing only, never authorization. Each path independently verifies
            # its own signature, issuer, audience, expiry and persisted owner.
            hint = jwt.decode(token, options={"verify_signature": False})
        except JWTError:
            raise HTTPException(401, "登录状态无效") from None
        return (
            local_user(token, db)
            if hint.get("iss") == LOCAL_ISSUER
            else cloud_user(token, db)
        )
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token)
    except JWTError:
        raise credentials_exception

    sub: str | None = payload.get("sub")
    token_type: str = payload.get("type", "access")
    jti: str | None = payload.get("jti")
    token_version = payload.get("token_version")
    if not sub or token_type != "access" or not jti or token_version is None:
        # Reject access tokens that predate the jti / token_version rollout —
        # they can't be revoked via the blacklist or invalidated by a password
        # change, so honouring them would create a permanently un-loggable
        # session. The frontend's 401 → refresh path then issues a fresh
        # compliant pair, so the disruption is bounded to one round-trip.
        raise credentials_exception

    if is_revoked(db, jti):
        raise credentials_exception

    # ``sub`` is the stable ``users.id``. Non-integer subs (e.g. legacy
    # username-based tokens from before the AUTH-IDENTITY migration) can't
    # match any row — reject rather than fall back to a username lookup.
    try:
        user_id = int(sub)
    except (TypeError, ValueError):
        raise credentials_exception

    user = db.query(User).filter(User.id == user_id).first()
    if user is None or not user.is_active:
        raise credentials_exception

    # Token-version gate: a password change bumps ``users.token_version``,
    # so every token minted before it fails here on next use.
    if token_version != user.token_version:
        raise credentials_exception
    from app.usage.runtime import bind
    import uuid

    bind(int(user.id), f"http:{uuid.uuid4().hex}", username=user.username)
    return user
