"""Pydantic schemas for /models HTTP endpoints.

Mirrors the request shapes used by ``app/api/model_runtime.py``:
runtime selection writes, per-user API key upserts, per-user provider
overrides. Per-user overrides carry their own SSRF / header-shape
validators alongside the schema definition — the bounds and the
validator must stay co-located to keep the contract self-documenting.
"""
from __future__ import annotations

import json

from pydantic import BaseModel, Field, field_validator

from app.core.ssrf import UrlNotSafe, validate_safe_url


# ── Limits / validators for the per-user provider settings (P6-M) ──
_API_BASE_MAX_LEN = 500
_ORG_ID_MAX_LEN = 100
_EXTRA_HEADERS_MAX_COUNT = 10
_EXTRA_HEADERS_MAX_VALUE_LEN = 500
_SYSTEM_RESERVED_HEADER_NAMES = {
    "authorization", "cookie", "host", "content-length", "content-type",
    "x-api-key", "anthropic-version",
}


class RuntimeSelectionUpdateRequest(BaseModel):
    """``PATCH /models/selection`` — pick which profile drives each role."""
    primary: str | None = Field(default=None, description="Primary LLM profile id")
    fast: str | None = Field(default=None, description="(internal) fast utility LLM, kept for back-compat")
    agent: str | None = Field(default=None, description="Function-calling agent profile id")
    mock_interview: str | None = Field(default=None, description="Mock-interview plan / interviewer LLM")


class APIKeyUpsertRequest(BaseModel):
    """``PUT /models/api-keys/{provider}`` — write a per-user provider key."""
    api_key: str = Field(..., min_length=4, description="Provider API key. Encrypted at rest; never echoed back.")


class ProviderSettingsUpdateRequest(BaseModel):
    """Per-user overrides for one provider (P6-M).

    Every field is optional; ``None`` = "don't touch this field".
    Pass an explicit empty string for ``api_base_override`` /
    ``organization_id`` to clear the override (revert to defaults).

    SSRF / shape validation happens in ``field_validator``s below so
    the API layer rejects bad input before service-layer DB writes.
    """
    enabled: bool | None = Field(
        default=None,
        description="Show this vendor card on the user's Models page.",
    )
    api_base_override: str | None = Field(
        default=None,
        description="HTTPS override URL for subscription / self-hosted endpoints. "
                    "Empty string = clear override.",
    )
    organization_id: str | None = Field(
        default=None,
        description="OpenAI org / Azure deployment / Aliyun project id. "
                    "Empty string = clear.",
    )
    extra_headers_json: str | None = Field(
        default=None,
        description="JSON-encoded {str: str} of additional headers (v1 only via "
                    "PATCH; no UI surface). Empty string = clear.",
    )

    @field_validator("api_base_override")
    @classmethod
    def _validate_api_base(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return v
        if len(v) > _API_BASE_MAX_LEN:
            raise ValueError(f"api_base too long (max {_API_BASE_MAX_LEN})")
        try:
            validate_safe_url(v, require_https=True)
        except UrlNotSafe as exc:
            # Surface the safety reason to the user — they can spot
            # "http://… not allowed" or "host resolves to private space"
            # immediately.
            raise ValueError(f"api_base rejected: {exc}") from exc
        return v

    @field_validator("organization_id")
    @classmethod
    def _validate_org_id(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return v
        if len(v) > _ORG_ID_MAX_LEN:
            raise ValueError(f"organization_id too long (max {_ORG_ID_MAX_LEN})")
        # No control chars (defence in depth — we'd be putting this in
        # an HTTP header value otherwise).
        if any(ord(c) < 0x20 for c in v):
            raise ValueError("organization_id contains control characters")
        return v

    @field_validator("extra_headers_json")
    @classmethod
    def _validate_extra_headers(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return v
        try:
            data = json.loads(v)
        except json.JSONDecodeError as exc:
            raise ValueError(f"extra_headers_json must be valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("extra_headers_json must encode a JSON object")
        if len(data) > _EXTRA_HEADERS_MAX_COUNT:
            raise ValueError(
                f"too many extra headers (max {_EXTRA_HEADERS_MAX_COUNT})",
            )
        for key, val in data.items():
            if not isinstance(key, str) or not isinstance(val, str):
                raise ValueError("extra_headers_json keys & values must be strings")
            if not key.strip():
                raise ValueError("extra_headers_json header name cannot be empty")
            if key.strip().lower() in _SYSTEM_RESERVED_HEADER_NAMES:
                # These are owned by the system (Authorization comes from
                # the user's API key, anthropic-version from our loader,
                # Host / Content-* from httpx). Letting the user override
                # would either break auth or silently bypass our SSRF.
                raise ValueError(
                    f"header {key!r} is system-controlled and cannot be set "
                    "via extra_headers_json",
                )
            if len(val) > _EXTRA_HEADERS_MAX_VALUE_LEN:
                raise ValueError(
                    f"header {key!r} value too long "
                    f"(max {_EXTRA_HEADERS_MAX_VALUE_LEN})",
                )
            if any(ord(c) < 0x20 for c in val):
                raise ValueError(
                    f"header {key!r} contains control characters",
                )
        # Re-serialise to normalise whitespace and ensure round-trip stability.
        return json.dumps(data, ensure_ascii=False)


__all__ = [
    "RuntimeSelectionUpdateRequest",
    "APIKeyUpsertRequest",
    "ProviderSettingsUpdateRequest",
]
