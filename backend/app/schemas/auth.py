"""Pydantic schemas for /auth + /me HTTP endpoints.

Mirrors the request / response shapes used by ``app/api/auth.py``.
Kept as a separate module so handlers, tests, and (eventually) FE
codegen all reference the same source of truth.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator


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


class ChangePasswordRequest(BaseModel):
    """Body for ``POST /auth/change-password``.

    Requires the current password (the endpoint re-verifies it) plus the new
    one. ``new_password`` carries a minimal length floor so the structured 422
    fires before we ever hash an obviously-too-short secret.
    """

    old_password: str
    new_password: str = Field(..., min_length=6, max_length=128)


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
    # page mounts. The legacy ``memory_recall_default`` alias used to
    # be emitted here too for pre-Stage-H clients, but the frontend
    # was migrated and now reads only the canonical name — the alias
    # emit was dead weight on every /me round-trip (audit cleanup).
    # ``MeUpdate`` still ACCEPTS the legacy name on input via Pydantic
    # ``populate_by_name`` so any stale PATCH client keeps working.
    global_memory_enabled: bool = False


class AvatarSetRequest(BaseModel):
    """Body for ``POST /me/avatar`` — set the avatar from a confirmed
    ``file_assets(purpose='avatar')`` upload (presigned flow)."""
    file_asset_id: str


__all__ = [
    "UserCreate",
    "Token",
    "RefreshRequest",
    "LogoutRequest",
    "EmailRequest",
    "ChangePasswordRequest",
    "MeUpdate",
    "MeResponse",
    "AvatarSetRequest",
]
