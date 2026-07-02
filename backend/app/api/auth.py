"""Auth + profile + avatar endpoints.

Security model:
- Stateless JWT with ``jti`` claim for revocation (see token_blacklist_service).
- Refresh rotates: each /refresh call invalidates the consumed refresh
  token's jti so stealing one ticket only buys until first rotation.
- /logout revokes both presented tokens (access via Authorization header,
  refresh via request body) so a real logout can't be undone by replay.
- /send-code and /register do not leak whether an email is registered.

Thin router: token/code protocol flow + HTTP status mapping. The
``users``-table work lives in ``services.auth.user_account_service``; the
avatar storage logic in ``services.auth.avatar_service``.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import OAuth2PasswordRequestForm
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import RATE_AUTH, RATE_UPLOAD, limiter
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_and_maybe_rehash,
    get_current_user,
    oauth2_scheme,
    token_claims_for,
)
from app.db.database import get_db
from app.models.user import User
from app.services.auth import avatar_service, user_account_service
from app.services.auth.token_blacklist_service import is_revoked, revoke
from app.services.auth.verification_code_service import (
    CodeError,
    assert_ip_not_locked,
    record_verify_failure_for_ip,
    request_code,
    reset_ip_failures,
    verify_code,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────
# Pydantic models live in app/schemas/auth.py — re-exported here so
# existing callers (`from app.api.auth import UserCreate`) keep working.
from app.schemas.auth import (  # noqa: E402, F401
    AvatarSetRequest,
    ChangePasswordRequest,
    EmailRequest,
    LogoutRequest,
    MeResponse,
    MeUpdate,
    RefreshRequest,
    Token,
    UserCreate,
)


# ── Token helpers ──────────────────────────────────────────────────────


async def _revoke_token_if_present(token: str | None) -> None:
    """Decode + revoke a token's jti. Best-effort — invalid tokens are no-ops.

    Used by /logout and /refresh to invalidate the consumed tokens.
    """
    if not token:
        return
    try:
        payload = decode_token(token)
    except JWTError:
        return  # already invalid → nothing to revoke
    jti = payload.get("jti")
    exp = payload.get("exp")
    if jti:
        await revoke(jti, exp=exp)


def _generic_400(detail_human: str) -> HTTPException:
    """One-stop 400 builder so endpoints can use the same wording everywhere.

    Helps avoid leaking which specific field of input was wrong on
    auth-adjacent endpoints (account enumeration mitigation).
    """
    return HTTPException(status_code=400, detail=detail_human)


# Business error codes for the REGISTER link. Registration deliberately
# trades a little enumeration exposure for UX: telling a returning user
# "this account already exists, just log in" beats making them wait on a
# verification code that will never arrive. LOGIN and password-reset stay
# generic (those links are the high-value enumeration targets). The codes
# are stable contract strings the frontend switches on; ``message`` is the
# default human text. Detail is a dict → the FE reads ``detail.code``.
ERR_EMAIL_ALREADY_REGISTERED = "EMAIL_ALREADY_REGISTERED"
ERR_USERNAME_ALREADY_REGISTERED = "USERNAME_ALREADY_REGISTERED"


def _conflict(code: str, message: str) -> HTTPException:
    """409 with a structured ``{code, message}`` detail body."""
    return HTTPException(status_code=409, detail={"code": code, "message": message})


# ── Endpoints ────────────────────────────────────────────────────────


@router.post("/send-code", response_model=dict)
@limiter.limit(RATE_AUTH)
async def send_verification_code(
    request: Request,
    response: Response,
    payload: EmailRequest,
    db: Session = Depends(get_db),
):
    """Generate and send a 6-digit code to the given email.

    Registration UX over enumeration secrecy: for ``purpose="register"`` an
    already-registered email returns ``409 EMAIL_ALREADY_REGISTERED`` so the
    user is told to log in instead of waiting on a code that never arrives.
    Mature consumer products do this; the residual enumeration exposure is
    accepted only for the register link. The high-value enumeration targets —
    LOGIN and password reset — keep generic responses elsewhere.
    """
    if payload.purpose == "register":
        if user_account_service.get_by_email(db, payload.email) is not None:
            raise _conflict(
                ERR_EMAIL_ALREADY_REGISTERED,
                "该邮箱已注册，请直接登录",
            )

    try:
        ttl = await request_code(payload.email, purpose=payload.purpose)  # type: ignore[arg-type]
    except CodeError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    return {"status": "sent", "expires_in": ttl}


@router.post("/register", response_model=dict)
@limiter.limit(RATE_AUTH)
async def register_user(
    request: Request,
    response: Response,
    user_in: UserCreate,
    db: Session = Depends(get_db),
):
    """Register a new user after verifying their email code.

    Duplicate username / email return an explicit ``409`` with a stable
    business code so the frontend can say "already registered, just log in".
    A *wrong code* still returns the generic 400 (a code attempt is the only
    thing a brute-forcer controls, so that branch stays opaque). Per the auth
    design, the duplicate-account checks run BEFORE code verification and do
    NOT consume the IP verification-failure budget — a returning user fat-
    fingering their own email shouldn't get the IP locked out.
    """
    generic_err = _generic_400("注册失败，请检查输入或重试")
    client_ip = request.client.host if request.client else None

    # IP lockout — blocks attackers who rotate emails to keep each
    # per-(email, purpose) counter under its own threshold.
    try:
        await assert_ip_not_locked(client_ip)
    except CodeError:
        raise generic_err

    # Duplicate-account checks first, and they don't count as verify failures.
    if user_account_service.get_by_username(db, user_in.username):
        raise _conflict(
            ERR_USERNAME_ALREADY_REGISTERED,
            "该用户名已被注册，请更换或直接登录",
        )
    if user_account_service.get_by_email(db, user_in.email):
        raise _conflict(
            ERR_EMAIL_ALREADY_REGISTERED,
            "该邮箱已注册，请直接登录",
        )

    try:
        await verify_code(user_in.email, user_in.code, purpose="register")
    except CodeError:
        await record_verify_failure_for_ip(client_ip)
        raise generic_err

    await reset_ip_failures(client_ip)

    user = user_account_service.create_user(
        db, username=user_in.username, email=user_in.email, password=user_in.password,
    )
    return {"message": "User registered successfully", "user_id": user.id}


@router.post("/login", response_model=Token)
@limiter.limit(RATE_AUTH)
def login_access_token(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    form_data: OAuth2PasswordRequestForm = Depends(),
):
    user = user_account_service.authenticate(db, form_data.username, form_data.password)
    if user is None:
        raise HTTPException(status_code=400, detail="用户名或密码错误")

    claims = token_claims_for(user)
    access_token = create_access_token(
        data=claims,
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    refresh_token = create_refresh_token(data=claims)
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


@router.post("/refresh", response_model=Token)
@limiter.limit(RATE_AUTH)
async def refresh_access_token(
    request: Request,
    response: Response,
    body: RefreshRequest,
    db: Session = Depends(get_db),
):
    """Rotate refresh tokens.

    On every successful refresh we:
      1. Verify the presented token is a valid, non-revoked refresh JWT.
      2. Revoke its jti so it cannot be reused.
      3. Issue a fresh access + refresh pair.

    A leaked refresh token therefore burns out the moment the legitimate
    holder refreshes — limiting the attacker to a single rotation window.
    """
    credentials_exception = HTTPException(
        status_code=401,
        detail="Invalid or expired refresh token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(body.refresh_token)
    except JWTError:
        raise credentials_exception

    sub = payload.get("sub")
    token_type = payload.get("type")
    jti = payload.get("jti")
    token_version = payload.get("token_version")
    if not sub or token_type != "refresh" or token_version is None:
        raise credentials_exception
    if await is_revoked(jti):
        raise credentials_exception

    try:
        user_id = int(sub)
    except (TypeError, ValueError):
        raise credentials_exception
    user = user_account_service.get_by_id(db, user_id)
    if user is None:
        raise credentials_exception

    # A password change bumps token_version, so a refresh token minted before
    # it is dead even if it hasn't expired and wasn't individually revoked.
    if token_version != user.token_version:
        raise credentials_exception

    # Revoke the consumed refresh token before issuing the new pair so a
    # double-spend race loses one of the two attempts.
    await revoke(jti, exp=payload.get("exp"))

    claims = token_claims_for(user)
    access_token = create_access_token(
        data=claims,
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    refresh_token = create_refresh_token(data=claims)
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


@router.post("/logout", response_model=dict)
@limiter.limit(RATE_AUTH)
async def logout(
    request: Request,
    response: Response,
    body: LogoutRequest | None = None,
    access_token: str = Depends(oauth2_scheme),
):
    """Revoke the caller's access token and (optionally) their refresh token.

    Idempotent: revoking an already-revoked / already-expired token is a no-op.
    The endpoint never reveals whether the tokens were valid.
    """
    await _revoke_token_if_present(access_token)
    if body and body.refresh_token:
        await _revoke_token_if_present(body.refresh_token)
    return {"status": "ok"}


@router.post("/change-password", response_model=dict)
@limiter.limit(RATE_AUTH)
def change_password(
    request: Request,
    response: Response,
    body: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Change the caller's password and invalidate every outstanding token.

    Requires the current password — a hijacked-but-still-logged-in session
    shouldn't be able to silently lock the real owner out. On success, in one
    commit we: rehash the new password, bump ``token_version`` (which kills
    ALL access + refresh tokens, including the one that authorized THIS
    request), and stamp ``password_changed_at``.

    We deliberately do NOT return a fresh token pair: the user re-logs in with
    the new password. The frontend's 401 → refresh → redirect flow takes them
    to /auth on their next call, since the old refresh token now fails the
    token-version check too.
    """
    valid, _ = verify_and_maybe_rehash(body.old_password, current_user.hashed_password)
    if not valid:
        raise HTTPException(status_code=400, detail="当前密码不正确")

    user_account_service.apply_password_change(db, current_user, body.new_password)
    return {"status": "ok", "message": "密码已修改，请使用新密码重新登录"}


# ── Profile ─────────────────────────────────────────────────────────────


def _serialize_me(user: User) -> MeResponse:
    return MeResponse(
        username=user.username,
        email=user.email,
        nickname=user.nickname,
        avatar_url=avatar_service.public_avatar_url(user),
        bio=user.bio,
        email_verified=bool(user.email_verified),
        created_at=user.created_at.isoformat() if user.created_at else "",
        updated_at=user.updated_at.isoformat() if user.updated_at else "",
        global_memory_enabled=bool(getattr(user, "global_memory_enabled", False)),
    )


@router.get("/me", response_model=MeResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return _serialize_me(current_user)


@router.patch("/me", response_model=MeResponse)
def update_me(
    payload: MeUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_account_service.update_profile(
        db, current_user,
        nickname=payload.nickname,
        avatar_url=payload.avatar_url,
        bio=payload.bio,
        global_memory_enabled=payload.global_memory_enabled,
    )
    return _serialize_me(current_user)


@router.post("/me/avatar", response_model=MeResponse)
@limiter.limit(RATE_UPLOAD)
async def set_avatar(
    request: Request,
    response: Response,
    body: AvatarSetRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Set the avatar from a confirmed ``file_assets(purpose='avatar')`` upload.

    The image was PUT straight to object storage via the unified presigned flow,
    so there is no server-receives-bytes path. Here we run the image safety check
    (declared type + size + magic bytes on the object head), then point
    ``users.avatar_url`` at the asset and mark it consumed. ``avatar_url`` stores
    the ``s3://`` URI; the serializer turns it into a presigned GET on /auth/me.
    """
    from app.services.uploads.file_asset_service import get_owned_file_asset

    asset = get_owned_file_asset(
        db, file_asset_id=body.file_asset_id,
        user_id=current_user.username, purpose="avatar",
    )
    if asset is None:
        raise HTTPException(status_code=404, detail="头像文件不存在")
    if asset.upload_status not in {"uploaded", "consumed"}:
        raise HTTPException(status_code=409, detail="头像尚未上传完成")
    if (asset.content_type or "") not in avatar_service.AVATAR_TYPES:
        raise HTTPException(status_code=400, detail=f"不支持的图片类型：{asset.content_type}")
    if asset.size_bytes is not None and asset.size_bytes > avatar_service.AVATAR_MAX_BYTES:
        raise HTTPException(status_code=413, detail="图片过大（>1MB），请压缩后再试")
    if not (asset.storage_uri or "").startswith("s3://"):
        raise HTTPException(status_code=400, detail="头像存储位置无效")

    # Magic-byte check on the uploaded bytes (the server never saw them during
    # the presigned PUT) — keeps a renamed executable from riding a permissive
    # image MIME into the user row.
    try:
        head = await asyncio.to_thread(avatar_service.read_object_head, asset.storage_uri, 32)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Avatar head read failed for user=%s: %s", current_user.username, exc)
        raise HTTPException(status_code=502, detail="无法读取已上传的头像，请重试") from exc
    if not avatar_service.matches_magic(asset.content_type, head):
        raise HTTPException(
            status_code=400, detail="文件内容与声明的图片类型不匹配，已拒绝",
        )

    # Known gap (deferred): the presigned PUT URL minted at upload-url time has a
    # 1h TTL and isn't revoked after this validation, so a user could re-PUT bytes
    # to their OWN key after the magic check passes (self-poisoning only — it only
    # affects where their own avatar renders). A future hardening would copy the
    # validated object to an immutable server key or shorten the upload TTL.
    avatar_service.swap_avatar(db, current_user, asset)
    return _serialize_me(current_user)
