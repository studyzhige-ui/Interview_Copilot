"""Auth + profile + avatar endpoints.

Security model:
- Stateless JWT with ``jti`` claim for revocation (see token_blacklist_service).
- Refresh rotates: each /refresh call invalidates the consumed refresh
  token's jti so stealing one ticket only buys until first rotation.
- /logout revokes both presented tokens (access via Authorization header,
  refresh via request body) so a real logout can't be undone by replay.
- /send-code and /register do not leak whether an email is registered.
"""
from __future__ import annotations

import io
import logging
import re
import uuid
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from fastapi.security import OAuth2PasswordRequestForm
from jose import JWTError
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import RATE_AUTH, RATE_UPLOAD, limiter
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
    get_password_hash,
    oauth2_scheme,
    verify_password,
)
from app.db.database import get_db
from app.models.user import User
from app.services.storage_service import (
    delete_local_uri,
    delete_s3_object,
    generate_presigned_get_url,
    is_local_uri,
    save_blob_to_local,
    upload_file_to_owned_key,
)
from app.services.token_blacklist_service import is_revoked, revoke
from app.services.verification_code_service import (
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


class UserCreate(BaseModel):
    username: str
    password: str
    email: EmailStr
    code: str = Field(..., description="6-digit email verification code")


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    # Optional — if omitted we still revoke the access token from the header.
    refresh_token: Optional[str] = None


class EmailRequest(BaseModel):
    email: EmailStr
    purpose: str = "register"  # "register" | "reset_password" | "change_email"


class MeUpdate(BaseModel):
    nickname: Optional[str] = Field(default=None, max_length=64)
    avatar_url: Optional[str] = Field(default=None, max_length=512)
    bio: Optional[str] = Field(default=None, max_length=2000)
    # PATCH /me can flip the user-level GLOBAL memory toggle. Frontend
    # exposes it in 个人中心; sessions without an explicit per-session
    # override inherit this value. ``None`` here means "don't touch" —
    # the handler only writes the column when the client actually
    # sends a value. Semantics: when False, the LLM does NOT see the
    # v3 memory bundle for this user; session-local context still
    # flows. See ``recall_policy`` module docstring for the full
    # contract.
    #
    # The ``memory_recall_default`` alias keeps in-flight frontend
    # builds (pre-Stage-H) writing the toggle correctly. Once the
    # frontend ships with ``global_memory_enabled`` everywhere this
    # alias can be retired in a follow-up.
    global_memory_enabled: Optional[bool] = Field(
        default=None, alias="memory_recall_default",
    )

    model_config = {"populate_by_name": True}

    @field_validator("avatar_url", mode="before")
    @classmethod
    def _reject_internal_avatar_schemes(cls, v):
        """Only http(s):// URLs are user-settable via PATCH.

        ``data:`` (legacy inline base64), ``s3://`` (backend-managed blob),
        and ``local://`` (backend fallback) are all internal storage forms.
        Letting a client submit them would either re-introduce the data:
        bloat we're migrating away from, or write an unverifiable / forged
        URI straight onto the user row.
        """
        if v is None:
            return v
        if not isinstance(v, str):
            raise ValueError("avatar_url must be a string")
        s = v.strip()
        if not s:
            return s
        lower = s.lower()
        for forbidden in ("data:", "s3://", "local://"):
            if lower.startswith(forbidden):
                raise ValueError(
                    "avatar_url must be a public http(s) URL; "
                    "use POST /me/avatar to upload an image."
                )
        if not (lower.startswith("http://") or lower.startswith("https://")):
            raise ValueError("avatar_url must start with http:// or https://")
        return s


class MeResponse(BaseModel):
    username: str
    email: Optional[str]
    nickname: Optional[str]
    avatar_url: Optional[str]
    bio: Optional[str]
    email_verified: bool
    created_at: str
    updated_at: str
    # User-level preferences. Today only one knob — surface it on the
    # same /me payload to avoid a second round-trip when the profile
    # page mounts. Emit BOTH the canonical ``global_memory_enabled``
    # AND the legacy ``memory_recall_default`` alias so a pre-Stage-H
    # frontend still sees the toggle state at the old key.
    global_memory_enabled: bool = False
    memory_recall_default: bool = False  # legacy alias — same value


# Avatar upload limits.
#   * content-type restricted to four common image MIMEs
#   * 1 MiB hard cap (browser-served data: URL goes straight into a DB row)
#   * magic-byte verification — the only way to keep a renamed .php from
#     landing in our user table with image/png MIME label
_AVATAR_MAX_BYTES = 1024 * 1024
_AVATAR_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}

# Each entry: list of valid magic-byte prefixes for the format. WEBP also
# requires the bytes 8..12 to equal "WEBP" since 4..8 is the file size.
_MAGIC_PREFIXES: dict[str, tuple[bytes, ...]] = {
    "image/png":  (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/gif":  (b"GIF87a", b"GIF89a"),
    # WEBP is RIFF + "WEBP" 4 bytes later; handled specially below.
    "image/webp": (b"RIFF",),
}


def _matches_magic(content_type: str, body: bytes) -> bool:
    """True iff ``body`` actually starts with the magic bytes for ``content_type``."""
    prefixes = _MAGIC_PREFIXES.get(content_type)
    if not prefixes:
        return False
    if content_type == "image/webp":
        # RIFF<size:4>WEBP<...>  — guard against the size bytes being anything.
        return len(body) >= 12 and body[:4] == b"RIFF" and body[8:12] == b"WEBP"
    return any(body.startswith(p) for p in prefixes)


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

    Account-enumeration defence: for ``purpose="register"`` we ALWAYS return a
    "sent" response, even when the email is already registered. We just don't
    actually issue/email a code in that case. A real registered user who
    tries to register their own email will fail at /register with the same
    generic 400 — they cannot distinguish "already taken" from "verification
    code wrong" by API response alone.
    """
    if payload.purpose == "register":
        existing = db.query(User).filter(User.email == payload.email).first()
        if existing is not None:
            logger.info(
                "send-code: ignoring register attempt for already-registered email"
            )
            # Lie convincingly: same shape, same approximate TTL.
            return {"status": "sent", "expires_in": settings.EMAIL_CODE_TTL_SECONDS}

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

    Returns the same generic error for "username taken" / "email taken" /
    "code wrong" so the attacker cannot tell which field tripped.
    """
    generic_err = _generic_400("注册失败，请检查输入或重试")
    client_ip = request.client.host if request.client else None

    # IP lockout — blocks attackers who rotate emails to keep each
    # per-(email, purpose) counter under its own threshold.
    try:
        await assert_ip_not_locked(client_ip)
    except CodeError:
        raise generic_err

    if db.query(User).filter(User.username == user_in.username).first():
        await record_verify_failure_for_ip(client_ip)
        raise generic_err
    if db.query(User).filter(User.email == user_in.email).first():
        await record_verify_failure_for_ip(client_ip)
        raise generic_err

    try:
        await verify_code(user_in.email, user_in.code, purpose="register")
    except CodeError:
        await record_verify_failure_for_ip(client_ip)
        raise generic_err

    await reset_ip_failures(client_ip)

    user = User(
        username=user_in.username,
        email=user_in.email,
        hashed_password=get_password_hash(user_in.password),
        email_verified=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"message": "User registered successfully", "user_id": user.id}


@router.post("/login", response_model=Token)
@limiter.limit(RATE_AUTH)
def login_access_token(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    form_data: OAuth2PasswordRequestForm = Depends(),
):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="用户名或密码错误")

    access_token = create_access_token(
        data={"sub": user.username},
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    refresh_token = create_refresh_token(data={"sub": user.username})
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

    username = payload.get("sub")
    token_type = payload.get("type")
    jti = payload.get("jti")
    if not username or token_type != "refresh":
        raise credentials_exception
    if await is_revoked(jti):
        raise credentials_exception

    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise credentials_exception

    # Revoke the consumed refresh token before issuing the new pair so a
    # double-spend race loses one of the two attempts.
    await revoke(jti, exp=payload.get("exp"))

    access_token = create_access_token(
        data={"sub": user.username},
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    refresh_token = create_refresh_token(data={"sub": user.username})
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


# ── Profile ─────────────────────────────────────────────────────────────


_LOCAL_AVATAR_URI_PREFIX = "local://avatars/"
_LOCAL_AVATAR_STATIC_PATH = "/api/v1/static/avatars/"


def _public_avatar_url(user: User) -> Optional[str]:
    """Translate the stored ``avatar_url`` to a browser-fetchable URL.

    Three storage shapes are supported AFTER the data:-URL migration ran:
      * ``s3://bucket/...``           → presigned GET URL (15-min TTL); the
        browser fetches bytes straight from S3 / MinIO.
      * ``local://avatars/<rel>...``  → ``/api/v1/static/avatars/<rel>`` —
        S3-fallback storage, served by FastAPI's StaticFiles mount.
      * ``http(s)://...``              → user-supplied public URL, verbatim.
      * ``data:...``                   → returns None. Should never appear
        after the migration; if it does, log a warning so the operator
        notices a missed row.
      * ``None`` / ``""``              → no avatar.
    """
    raw = (user.avatar_url or "").strip()
    if not raw:
        return None
    if raw.startswith("s3://"):
        try:
            return generate_presigned_get_url(raw, expiration=900)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Presign avatar GET failed for user=%s: %s", user.username, exc,
            )
            return None
    if raw.startswith(_LOCAL_AVATAR_URI_PREFIX):
        # Strip the ``local://avatars/`` prefix and prepend the static mount
        # so the browser hits FastAPI for the bytes. URL-quote the segments
        # so spaces / unicode in usernames don't break the route.
        rel_under_mount = raw[len(_LOCAL_AVATAR_URI_PREFIX):]
        from urllib.parse import quote
        return f"{_LOCAL_AVATAR_STATIC_PATH}{quote(rel_under_mount, safe='/')}"
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    if raw.startswith("data:"):
        # Migration didn't reach this row; log loudly so the operator can
        # re-run scripts.migrate_avatars. We refuse to render it inline so
        # the bloat doesn't keep leaving the DB on every /auth/me.
        logger.warning(
            "Avatar for user=%s is still a data: URL — run "
            "`python scripts/migrate_avatars.py` to migrate it.",
            user.username,
        )
        return None
    # Anything else (e.g. ``local://resumes/...``, a stray absolute path) is
    # not avatar-shaped — refuse rather than leak server-internal URIs.
    logger.warning(
        "Unrecognized avatar_url scheme for user=%s: %r", user.username, raw[:32],
    )
    return None


def _serialize_me(user: User) -> MeResponse:
    return MeResponse(
        username=user.username,
        email=user.email,
        nickname=user.nickname,
        avatar_url=_public_avatar_url(user),
        bio=user.bio,
        email_verified=bool(user.email_verified),
        created_at=user.created_at.isoformat() if user.created_at else "",
        updated_at=user.updated_at.isoformat() if user.updated_at else "",
        global_memory_enabled=bool(getattr(user, "global_memory_enabled", False)),
        memory_recall_default=bool(getattr(user, "global_memory_enabled", False)),
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
    changed = False
    if payload.nickname is not None:
        current_user.nickname = payload.nickname.strip() or None
        changed = True
    if payload.avatar_url is not None:
        current_user.avatar_url = payload.avatar_url.strip() or None
        changed = True
    if payload.bio is not None:
        current_user.bio = payload.bio.strip() or None
        changed = True
    if payload.global_memory_enabled is not None:
        # Don't normalize to a string truthy/falsy — Pydantic already
        # gave us a real bool, just persist it. ``False`` is a legitimate
        # write (the opt-in default), so we don't filter on truthiness.
        current_user.global_memory_enabled = bool(payload.global_memory_enabled)
        changed = True
    if changed:
        db.add(current_user)
        db.commit()
        db.refresh(current_user)
    return _serialize_me(current_user)


def _avatar_object_key(user: User, content_type: str) -> str:
    """Per-user, per-upload object key under the avatars/ prefix.

    Including a UUID per upload (instead of a stable name) means a stale
    presigned URL pointing at the previous avatar can't accidentally serve
    fresh bytes — when the row updates, the old object key dies on the
    next ``delete_s3_object`` cleanup.
    """
    ext = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }.get(content_type, ".bin")
    safe_user = re.sub(r"[^A-Za-z0-9._-]+", "_", user.username).strip("._") or "anon"
    return f"avatars/{safe_user}/{uuid.uuid4().hex}{ext}"


def _store_avatar_blob(
    body: bytes,
    object_key: str,
    content_type: str,
    username: str,
) -> str:
    """Persist avatar bytes — S3 preferred, ``local://`` fallback on outage.

    Returns the canonical storage URI (``s3://...`` or ``local://avatars/...``)
    to be written into ``users.avatar_url``. The two forms are interchangeable
    downstream: the serializer translates each one to a browser-fetchable
    URL via :func:`_public_avatar_url`.
    """
    # 1) Preferred path: S3 / MinIO. ``upload_file_to_owned_key`` itself
    # falls back to ``_fallback_local_save`` (returning an absolute path)
    # on connection / client errors — but that legacy fallback shape is
    # opaque to our serializer. So we sidestep it: catch the S3 client
    # exception ourselves and call ``save_blob_to_local`` which returns a
    # well-formed ``local://`` URI we know how to serve.
    try:
        # ``upload_file_to_owned_key`` swallows ClientError + general
        # Exception and routes both to the legacy local fallback (absolute
        # path). To detect "did S3 actually work?" cleanly, talk to the
        # boto3 client directly here.
        from app.services.storage_service import s3_client, storage_uri_for_key
        from app.core.config import settings as _s
        s3_client.upload_fileobj(
            io.BytesIO(body),
            _s.S3_BUCKET_NAME,
            object_key,
            ExtraArgs={"ContentType": content_type},
        )
        return storage_uri_for_key(object_key)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Avatar S3 upload failed for user=%s; falling back to local: %s",
            username, exc,
        )

    # 2) Fallback path: write under STORAGE_DIR/avatars/... and record a
    # ``local://avatars/...`` URI. /api/v1/static/avatars/ mount serves
    # the bytes to the browser without needing S3 to recover.
    return save_blob_to_local(body, object_key)


def _delete_previous_avatar(previous_uri: str) -> None:
    """Best-effort cleanup of whichever store the previous avatar lived in.

    Failure is logged but never re-raised — orphan blobs are an operational
    annoyance, not a correctness problem.
    """
    if not previous_uri:
        return
    if previous_uri.startswith("s3://"):
        try:
            delete_s3_object(previous_uri)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to delete previous avatar %s: %s", previous_uri, exc)
    elif is_local_uri(previous_uri):
        # ``delete_local_uri`` is already best-effort.
        delete_local_uri(previous_uri)
    # data: / http(s):// / unknown — nothing on disk to clean.


@router.post("/me/avatar", response_model=MeResponse)
@limiter.limit(RATE_UPLOAD)
async def upload_avatar(
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload an avatar. Bytes go to S3 if available, otherwise local fallback.

    Either way ``users.avatar_url`` stores an opaque URI (never a base64
    data: URL); the serializer turns it into a browser-fetchable URL on
    each /auth/me response.
    """
    if file.content_type not in _AVATAR_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的图片类型：{file.content_type}",
        )
    body = await file.read()
    if len(body) > _AVATAR_MAX_BYTES:
        raise HTTPException(status_code=413, detail="图片过大（>1MB），请压缩后再试")
    if not body:
        raise HTTPException(status_code=400, detail="空文件")
    if not _matches_magic(file.content_type, body):
        # Browser said it was image/png but the bytes say otherwise — possibly
        # a renamed executable / PHP script trying to ride a permissive MIME.
        raise HTTPException(
            status_code=400,
            detail="文件内容与声明的图片类型不匹配，已拒绝",
        )

    previous_uri = (current_user.avatar_url or "").strip()
    object_key = _avatar_object_key(current_user, file.content_type)

    try:
        new_uri = _store_avatar_blob(body, object_key, file.content_type, current_user.username)
    except Exception as exc:  # noqa: BLE001
        # Both S3 and local-fallback failed (e.g. disk full + S3 down).
        # That's an actual server problem — surface a 5xx.
        logger.error("Avatar storage exhausted for user=%s: %s", current_user.username, exc)
        raise HTTPException(
            status_code=503,
            detail="头像存储暂不可用，请稍后再试",
        ) from exc

    current_user.avatar_url = new_uri
    db.add(current_user)
    db.commit()
    db.refresh(current_user)

    _delete_previous_avatar(previous_uri)
    return _serialize_me(current_user)
