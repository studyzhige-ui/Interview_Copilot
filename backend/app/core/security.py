"""JWT issuance, password hashing, and the FastAPI auth dependency.

Every token carries a ``jti`` (random UUID hex) so it can be revoked via
Redis blacklist on logout or refresh-rotation. See
``app.services.auth.token_blacklist_service``.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from pwdlib.hashers.bcrypt import BcryptHasher
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import get_db
from app.models.user import User
from app.services.auth.token_blacklist_service import is_revoked

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


# ── Password hashing (pwdlib: Argon2id default + bcrypt legacy verify) ──
#
# pwdlib is FastAPI's currently-recommended password-hashing library
# (the official docs at fastapi.tiangolo.com/tutorial/security use it
# now — passlib's maintainer effectively stopped shipping releases in
# 2020 and the bcrypt>=5.x incompatibility is a ticking timebomb).
#
# Algorithm choice:
#   * Argon2id is the 2015 Password Hashing Competition winner — the
#     current best-in-class against GPU/ASIC attackers. Default
#     parameters from pwdlib are calibrated for ~300ms hash time on
#     modern server hardware, which dominates the password-bruteforce
#     economy.
#   * BcryptHasher is kept in the verifier list ONLY so users whose
#     password rows still carry the legacy bcrypt hash from the
#     pre-pwdlib era can log in. ``verify_and_update`` below upgrades
#     their hash to Argon2id on the next successful login — within a
#     few weeks of active users the table will be entirely Argon2id
#     and we can drop BcryptHasher.
#
# pwdlib's hashers list is order-sensitive: the FIRST entry is what
# new hashes use; subsequent entries are tried in order for verify.
# So new accounts produce Argon2id; existing bcrypt rows verify
# through the second hasher and get re-hashed.
_password_hash = PasswordHash((Argon2Hasher(), BcryptHasher()))


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Constant-time verify against any pwdlib-supported algorithm.

    Returns False (instead of raising) when the hash is malformed,
    unrecognised, or the password isn't a string — matches the
    legacy bcrypt-only helper's contract. The 14 tests in
    test_security.py pin this.

    pwdlib raises ``UnknownHashError`` when the hash prefix doesn't
    match any configured hasher (argon2id / bcrypt) — for our API
    that's just "wrong password" because the hash is garbage data.
    """
    from pwdlib.exceptions import UnknownHashError

    try:
        if isinstance(hashed_password, bytes):
            hashed_password = hashed_password.decode("utf-8")
        return _password_hash.verify(plain_password, hashed_password)
    except (ValueError, TypeError, UnknownHashError):
        return False


def get_password_hash(password: str) -> str:
    """Hash with Argon2id — the first hasher in the recommended list."""
    return _password_hash.hash(password)


def verify_and_maybe_rehash(
    plain_password: str,
    hashed_password: str,
) -> tuple[bool, str | None]:
    """Verify AND upgrade legacy hashes in one step.

    Returns ``(valid, new_hash)``. ``new_hash`` is non-None when the
    stored hash was a legacy form (e.g. bcrypt) — callers should
    persist it via ``UPDATE users SET hashed_password = <new_hash>``
    so the next login uses the upgraded algorithm. Failure mode
    matches ``verify_password`` (returns ``(False, None)``).
    """
    from pwdlib.exceptions import UnknownHashError

    try:
        if isinstance(hashed_password, bytes):
            hashed_password = hashed_password.decode("utf-8")
        return _password_hash.verify_and_update(plain_password, hashed_password)
    except (ValueError, TypeError, UnknownHashError):
        return False, None


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
