"""Independent local business capability; never a Supabase account session."""

from __future__ import annotations

from datetime import timedelta
import uuid

import jwt
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.passwords import get_password_hash, verify_password
from app.core.token_blacklist import is_revoked
from app.db.types import utc_now
from app.models.external_identity import ExternalIdentity, LocalUnlockCredential
from app.models.user import User
from app.identity.application.supabase_auth import issuer, unauthorized

LOCAL_ISSUER = "interview-copilot-local"
LOCAL_AUDIENCE = "interview-copilot-local-business"


def require_local_key():
    if len(settings.SECRET_KEY) < 32:
        raise HTTPException(503, "本地安全密钥尚未配置，暂不能设置或使用本地解锁")


def enroll(db: Session, user: User, password: str):
    require_local_key()
    user = (
        db.query(User)
        .filter_by(id=user.id)
        .with_for_update()
        .populate_existing()
        .one_or_none()
    )
    if user is None or not user.is_active:
        raise unauthorized()
    row = (
        db.query(LocalUnlockCredential)
        .filter_by(user_id=user.id)
        .with_for_update()
        .one_or_none()
    )
    if row is None:
        row = LocalUnlockCredential(user_id=user.id, credential_version=1)
        db.add(row)
    else:
        row.credential_version += 1
    row.password_hash = get_password_hash(password)
    row.failed_attempts = 0
    row.locked_until = None
    row.updated_at = utc_now()
    db.commit()


def unlock(db: Session, email: str, password: str) -> str:
    require_local_key()
    identity = (
        db.query(ExternalIdentity)
        .filter_by(issuer=issuer(), email=email.strip().lower())
        .one_or_none()
    )
    row = (
        db.query(LocalUnlockCredential)
        .filter_by(user_id=identity.user_id if identity else -1)
        .with_for_update()
        .one_or_none()
    )
    user = db.get(User, identity.user_id) if identity else None
    now = utc_now()
    if not row or not user or not user.is_active:
        raise unauthorized()
    if row.locked_until and row.locked_until > now:
        raise HTTPException(429, "本地解锁尝试过多，请稍后重试")
    if not verify_password(password, row.password_hash):
        row.failed_attempts += 1
        if row.failed_attempts >= 5:
            row.locked_until = now + timedelta(minutes=5)
        db.commit()
        raise unauthorized()
    row.failed_attempts = 0
    row.locked_until = None
    # Capture the verified generation BEFORE releasing the lock. Production
    # sessions expire ORM attributes on commit; rereading afterwards could mint
    # a new-generation token from a password checked against the old generation.
    claims = {
        "iss": LOCAL_ISSUER,
        "aud": LOCAL_AUDIENCE,
        "sub": str(user.id),
        "type": "local_unlock",
        "scope": "local_business",
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": now + timedelta(hours=8),
        "token_version": user.token_version,
        "credential_version": row.credential_version,
    }
    encoded = jwt.encode(claims, settings.SECRET_KEY, algorithm="HS256")
    db.commit()
    return encoded


def decode_local_token(token: str) -> dict:
    require_local_key()
    return jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=["HS256"],
        issuer=LOCAL_ISSUER,
        audience=LOCAL_AUDIENCE,
        options={
            "require": [
                "sub",
                "exp",
                "iat",
                "jti",
                "token_version",
                "credential_version",
            ]
        },
    )


def local_user(token: str, db: Session) -> User:
    try:
        claims = decode_local_token(token)
        user = db.get(User, int(claims["sub"]))
        row = db.get(LocalUnlockCredential, int(claims["sub"]))
        identity = db.get(ExternalIdentity, int(claims["sub"]))
        if (
            claims.get("type") != "local_unlock"
            or claims.get("scope") != "local_business"
            or not user
            or not user.is_active
            or not row
            or not identity
            or identity.issuer != issuer()
            or claims["token_version"] != user.token_version
            or claims["credential_version"] != row.credential_version
            or is_revoked(db, claims["jti"])
        ):
            raise unauthorized()
        return user
    except (jwt.PyJWTError, ValueError, TypeError, KeyError):
        raise unauthorized() from None
