"""Unified identity onboarding; all product records stay in the local database."""

from __future__ import annotations

import time
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import RATE_AUTH, limiter
from app.core.security import oauth2_scheme
from app.core.token_blacklist import is_revoked
from app.db.database import get_db
from app.identity.application import local_unlock, supabase_auth
from app.models.external_identity import ExternalIdentity, LocalUnlockCredential
from app.models.user import User

router = APIRouter()


class BindProfileRequest(BaseModel):
    legacy_username: str | None = Field(default=None, min_length=1, max_length=320)
    legacy_password: str | None = Field(default=None, max_length=1024)


class UnlockRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=1024)


class UnlockSetupRequest(BaseModel):
    password: str = Field(min_length=12, max_length=128)


def verified_online_claims(token: str, db: Session) -> dict:
    claims = supabase_auth.verify_cloud_token(token, online=True)
    if is_revoked(db, supabase_auth.token_identity(token)):
        raise supabase_auth.unauthorized()
    return claims


def require_recent_password(claims: dict):
    now = time.time()
    if not any(
        isinstance(item, dict)
        and item.get("method") == "password"
        and isinstance(item.get("timestamp"), (int, float))
        and 0 <= now - item["timestamp"] <= 300
        for item in claims.get("amr", [])
    ):
        raise HTTPException(
            401, "请先用统一账号密码重新登录，再执行本地账号关联或解锁设置"
        )


@router.get("/config")
def auth_config():
    return {
        "provider": settings.AUTH_PROVIDER,
        "email_delivery": settings.SUPABASE_EMAIL_DELIVERY
        if settings.AUTH_PROVIDER == "supabase"
        else None,
        "supabase_url": settings.SUPABASE_URL
        if settings.AUTH_PROVIDER == "supabase"
        else None,
        "publishable_key": settings.SUPABASE_PUBLISHABLE_KEY
        if settings.AUTH_PROVIDER == "supabase"
        else None,
    }


@router.post("/supabase/session")
@limiter.limit(RATE_AUTH)
def bind_local_profile(
    request: Request,
    response: Response,
    body: BindProfileRequest,
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db, scope="function"),
):
    claims = verified_online_claims(token, db)
    if body.legacy_username:
        require_recent_password(claims)
    user = supabase_auth.bind_profile(
        db,
        claims,
        legacy_username=body.legacy_username,
        legacy_password=body.legacy_password,
    )
    from app.api.auth import _serialize_me

    return {
        "profile": _serialize_me(user),
        "local_unlock_enabled": db.get(LocalUnlockCredential, user.id) is not None,
    }


@router.post("/local-unlock/setup")
@limiter.limit(RATE_AUTH)
def setup_local_unlock(
    request: Request,
    response: Response,
    body: UnlockSetupRequest,
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db, scope="function"),
):
    claims = verified_online_claims(token, db)
    require_recent_password(claims)
    identity = (
        db.query(ExternalIdentity)
        .filter_by(issuer=claims["iss"], subject=claims["sub"])
        .one_or_none()
    )
    user = db.get(User, identity.user_id) if identity else None
    if not user or not user.is_active:
        raise supabase_auth.unauthorized()
    local_unlock.enroll(db, user, body.password)
    return {"status": "ok", "message": "已设置独立的本地解锁；资料仍保存在当前电脑"}


@router.post("/local-unlock")
@limiter.limit(RATE_AUTH)
def unlock_local_profile(
    request: Request,
    response: Response,
    body: UnlockRequest,
    db: Session = Depends(get_db, scope="function"),
):
    if settings.AUTH_PROVIDER != "supabase":
        raise HTTPException(409, "当前安装使用原本地账号登录")
    token = local_unlock.unlock(db, str(body.email), body.password)
    return {"access_token": token, "refresh_token": "", "token_type": "bearer"}
