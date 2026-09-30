"""Verify a Supabase identity; preserve the local owner and business-data boundary.

Asymmetric keys use bounded JWKS discovery. Legacy HS256 projects verify with
Auth's /user endpoint, never by shipping a shared signing secret to the desktop.
A valid JWT is not a claim of instant cloud-session revocation. Identity binding
and unlock enrollment additionally require an online, confirmed Auth user.
"""

from __future__ import annotations

import hashlib
import uuid
from functools import lru_cache

import httpx
import jwt
from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.token_blacklist import is_revoked
from app.models.external_identity import ExternalIdentity
from app.models.user import User


def unauthorized():
    return HTTPException(
        401, "登录状态无效，请重新登录", headers={"WWW-Authenticate": "Bearer"}
    )


def issuer() -> str:
    return settings.SUPABASE_URL.rstrip("/") + "/auth/v1"


def token_identity(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@lru_cache(maxsize=4)
def _jwks_client(url: str):
    return jwt.PyJWKClient(
        url + "/.well-known/jwks.json", cache_keys=False, lifespan=300, timeout=5
    )


def online_user(token: str) -> dict:
    try:
        response = httpx.get(
            issuer() + "/user",
            headers={
                "apikey": settings.SUPABASE_PUBLISHABLE_KEY,
                "Authorization": f"Bearer {token}",
            },
            timeout=8.0,
            follow_redirects=False,
        )
    except httpx.RequestError:
        raise HTTPException(503, "账号服务暂时不可用；可使用已设置的本地解锁") from None
    if response.status_code in (401, 403, 404):
        raise unauthorized()
    if response.status_code != 200:
        raise HTTPException(503, "账号服务暂时不可用，请稍后重试")
    try:
        user = response.json()
        if not isinstance(user, dict) or not user.get("email_confirmed_at"):
            raise unauthorized()
        return user
    except ValueError:
        raise HTTPException(503, "账号服务响应无效") from None


def verify_cloud_token(token: str, *, online: bool = False) -> dict:
    if settings.AUTH_PROVIDER != "supabase":
        raise HTTPException(409, "当前安装未启用统一账号")
    try:
        if len(token) > 16384:
            raise unauthorized()
        untrusted = jwt.decode(token, options={"verify_signature": False})
        if untrusted.get("iss") != issuer():
            raise unauthorized()
        header = jwt.get_unverified_header(token)
        algorithm = header.get("alg")
        user = None
        options = {"require": ["sub", "iss", "aud", "exp", "iat", "session_id"]}
        if algorithm in {"RS256", "ES256"}:
            signing_key = _jwks_client(issuer()).get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=[algorithm],
                audience="authenticated",
                issuer=issuer(),
                options=options,
            )
        elif algorithm == "HS256":
            # Only Auth knows the symmetric secret. Validate with Auth before
            # reading claims; explicitly retain all semantic JWT checks.
            user = online_user(token)
            payload = jwt.decode(
                token,
                options={
                    **options,
                    "verify_signature": False,
                    "verify_exp": True,
                    "verify_iat": True,
                    "verify_aud": True,
                    "verify_iss": True,
                    "verify_nbf": True,
                },
                audience="authenticated",
                issuer=issuer(),
            )
        else:
            raise unauthorized()
        if not isinstance(payload.get("session_id"), str):
            raise unauthorized()
        payload["sub"] = str(uuid.UUID(payload["sub"]))
        uuid.UUID(payload["session_id"])
        if payload.get("role") != "authenticated" or payload.get("is_anonymous", False):
            raise unauthorized()
        if online and user is None:
            user = online_user(token)
        if user is not None and (
            user.get("id") != payload["sub"] or not user.get("email")
        ):
            raise unauthorized()
        if user is not None:
            payload["email"] = user["email"]
        return payload
    except jwt.PyJWKClientConnectionError:
        raise HTTPException(503, "无法验证账号签名；可使用已设置的本地解锁") from None
    except (jwt.PyJWTError, ValueError, TypeError, KeyError):
        raise unauthorized() from None


def cloud_user(token: str, db: Session) -> User:
    claims = verify_cloud_token(token)
    if is_revoked(db, token_identity(token)):
        raise unauthorized()
    identity = (
        db.query(ExternalIdentity)
        .filter_by(issuer=claims["iss"], subject=claims["sub"])
        .one_or_none()
    )
    if identity is None:
        raise HTTPException(
            409,
            detail={
                "code": "LOCAL_PROFILE_REQUIRED",
                "message": "请先建立或关联当前电脑的本地资料空间",
            },
        )
    user = db.get(User, identity.user_id)
    if user is None or not user.is_active:
        raise unauthorized()
    return user


def bind_profile(
    db: Session,
    claims: dict,
    *,
    legacy_username: str | None = None,
    legacy_password: str | None = None,
) -> User:
    from app.core.passwords import verify_password

    existing = (
        db.query(ExternalIdentity)
        .filter_by(issuer=claims["iss"], subject=claims["sub"])
        .one_or_none()
    )
    if existing:
        user = db.get(User, existing.user_id)
        if user is None or not user.is_active:
            raise unauthorized()
        if legacy_username and legacy_username != user.username:
            raise HTTPException(
                409, "此统一账号已经关联另一份本地资料，不能自动转移所有权"
            )
        return user
    email = str(claims.get("email", "")).strip().lower()
    if not email or len(email) > 320:
        raise unauthorized()
    try:
        if legacy_username:
            user = db.query(User).filter_by(username=legacy_username).one_or_none()
            if (
                user is None
                or not user.is_active
                or not verify_password(legacy_password or "", user.hashed_password)
            ):
                raise unauthorized()
            if db.get(ExternalIdentity, user.id) is not None:
                raise HTTPException(409, "本地资料已关联统一账号")
            user.token_version += 1  # Retire all legacy local-login sessions.
        else:
            # Email equality is never proof of ownership. Require both credentials.
            if db.query(User.id).filter(func.lower(User.email) == email).first():
                raise HTTPException(
                    409,
                    detail={
                        "code": "LOCAL_ACCOUNT_EXISTS",
                        "message": "当前电脑已有同邮箱资料，请用原本地账号密码关联",
                    },
                )
            user = User(
                username="supabase_" + uuid.UUID(claims["sub"]).hex,
                email=email,
                hashed_password="!external-identity-no-local-password",
                email_verified=True,
                is_active=True,
            )
            db.add(user)
            db.flush()
        db.add(
            ExternalIdentity(
                user_id=user.id,
                issuer=claims["iss"],
                subject=claims["sub"],
                email=email,
            )
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        # Concurrent binding never creates two owners or leaks DB details.
        identity = (
            db.query(ExternalIdentity)
            .filter_by(issuer=claims["iss"], subject=claims["sub"])
            .one_or_none()
        )
        if identity:
            owner = db.get(User, identity.user_id)
            if (
                owner
                and owner.is_active
                and (not legacy_username or owner.username == legacy_username)
            ):
                return owner
        raise HTTPException(409, "资料空间关联冲突，请重试；已有资料未被转移") from None
    db.refresh(user)
    return user
