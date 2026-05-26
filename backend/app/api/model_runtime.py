import asyncio
import json
import logging
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.core.ssrf import UrlNotSafe, validate_safe_url
from app.db.database import get_db
from app.models.user import User
from app.core.model_registry import (
    _get_all_profiles,
    _serialize_profile,
    get_async_openai_client,
    get_profile,
    get_profile_for_role,
    get_runtime_selection,
    profile_ready,
    update_runtime_selection,
    validate_role_update,
)
from app.rag.embeddings import refresh_primary_llm
from app.services.model_sources.pipeline import load_catalog, refresh_catalog

logger = logging.getLogger(__name__)

router = APIRouter(tags=["models"])


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
    primary: str | None = Field(default=None, description="Primary LLM profile id")
    fast: str | None = Field(default=None, description="(internal) fast utility LLM, kept for back-compat")
    agent: str | None = Field(default=None, description="Function-calling agent profile id")
    mock_interview: str | None = Field(default=None, description="Mock-interview plan / interviewer LLM")


class APIKeyUpsertRequest(BaseModel):
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


@router.get("/models/catalog")
async def api_model_catalog(
    current_user: User = Depends(get_current_user),
):
    """List every profile + this user's runtime selection.

    Cached per-user for 60 s — ``list_profiles`` enumerates ~30 profiles
    and checks reachability for each, which is expensive enough that the
    Models page + the ChatPanel "refresh on focus" both noticeably stutter
    without it. Invalidated by /models/api-keys writes (see upsert/delete
    handlers below).
    """
    from app.services.cache_service import cached

    async def _build():
        selection = get_runtime_selection(user_id=current_user.username)
        # Pull the LiteLLM-driven catalog from the Redis pipeline cache.
        # ``load_catalog`` doesn't hit the vendor itself — that's the
        # daily Celery beat's job. The serialization layer below joins
        # each ``ModelEntry`` with its ``ProviderDefaults`` and tags
        # per-user state (ready flag, selected_for).
        from app.core.model_registry import repopulate_profile_cache
        grouped = await load_catalog()
        # Hint the sync profile cache with what we just read so chat
        # paths in this process don't take a Redis round-trip on the
        # next call.
        if grouped:
            repopulate_profile_cache(grouped)
        profiles_map = _get_all_profiles()
        profiles = [
            _serialize_profile(p, selection, current_user.username)
            for p in profiles_map.values()
        ]
        return {
            "status": "success",
            "selection": selection,
            "profiles": profiles,
        }

    return await cached(
        f"models:catalog:{current_user.username}",
        ttl=60,
        loader=_build,
    )


@router.post("/models/refresh-catalog")
async def refresh_model_catalog(
    current_user: User = Depends(get_current_user),
):
    """Force-refresh the LiteLLM-driven catalog.

    P6-L: data source is LiteLLM's public model_prices JSON, not per-vendor
    /v1/models discovery. ``refresh_catalog`` re-fetches the JSON with
    layer-3 protection (retry → schema validate → last-known-good
    fallback), persists per-provider entries to Redis, and updates the
    process-local profile cache. Also drops the per-user 60-s wrapper
    so this user sees the fresh entries on their very next read.
    """
    from app.services.cache_service import invalidate
    from app.core.model_registry import repopulate_profile_cache

    grouped = await refresh_catalog()
    repopulate_profile_cache(grouped)
    await invalidate(f"models:catalog:{current_user.username}")

    selection = get_runtime_selection(user_id=current_user.username)
    profiles_map = _get_all_profiles()
    profiles = [
        _serialize_profile(p, selection, current_user.username)
        for p in profiles_map.values()
    ]
    return {
        "status": "refreshed",
        "providers_refreshed": len(grouped),
        "profiles_total": len(profiles),
        "profiles": profiles,
    }


@router.get("/models/runtime")
async def api_model_runtime(
    current_user: User = Depends(get_current_user),
):
    uid = current_user.username
    selection = get_runtime_selection(user_id=uid)
    return {
        "status": "success",
        "selection": selection,
        "resolved": {
            role: {
                "profile_id": profile.id,
                "provider": profile.provider,
                "model": profile.model,
                "display_name": profile.display_name,
            }
            for role, profile in {
                "primary": get_profile_for_role("primary", user_id=uid),
                "fast": get_profile_for_role("fast", user_id=uid),
                "agent": get_profile_for_role("agent", user_id=uid),
                "mock_interview": get_profile_for_role("mock_interview", user_id=uid),
            }.items()
        },
    }


async def _ping_one(profile_id: str, user_id: str | None = None) -> dict:
    """Issue a minimal completion to check the provider/key is reachable.

    Reuses the per-(user_id, profile_id) cached AsyncOpenAI client from the
    registry — successive pings of the same profile share the same TLS
    connection pool instead of creating a fresh client (with handshake) for
    every call. Never raises.
    """
    started = time.perf_counter()
    try:
        profile = get_profile(profile_id)
    except ValueError as exc:
        return {"profile_id": profile_id, "ok": False, "latency_ms": 0, "error": str(exc)}
    if not profile_ready(profile, user_id=user_id):
        return {
            "profile_id": profile_id, "ok": False, "latency_ms": 0,
            "error": f"未配置 {profile.api_key_env}",
        }
    try:
        client = get_async_openai_client(profile, user_id=user_id)
        # 1-token completion — cheapest reachable signal.
        await asyncio.wait_for(
            client.chat.completions.create(
                model=profile.model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
                temperature=0,
            ),
            timeout=10.0,
        )
        return {
            "profile_id": profile_id, "ok": True,
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }
    except asyncio.TimeoutError:
        return {
            "profile_id": profile_id, "ok": False,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "error": "超时",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "profile_id": profile_id, "ok": False,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "error": f"{type(exc).__name__}: {exc}"[:200],
        }


# ── User API keys — encrypted per-user / per-provider storage ───────────


@router.get("/models/api-keys")
def list_my_api_keys(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the user's configured providers + masked hints.

    Never includes plaintext. Frontend uses this to render
    "✓ 已配置 (sk-***abcd)" badges per vendor card.
    """
    from app.services.user_api_key_service import list_user_api_keys
    return {"keys": list_user_api_keys(current_user.username, db=db)}


@router.put("/models/api-keys/{provider}")
async def upsert_my_api_key(
    provider: str,
    payload: APIKeyUpsertRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Encrypt-and-store the user's key for one provider.

    The plaintext is dropped after encryption; subsequent GETs only see the
    masked form. To replace, just PUT again — it overwrites.
    """
    from app.services.cache_service import invalidate
    from app.services.user_api_key_service import set_user_api_key
    try:
        result = set_user_api_key(
            current_user.username, provider, payload.api_key, db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # Refresh the LLM cache so the next request uses the new key.
    from app.core.model_registry import clear_llm_cache_for_provider
    clear_llm_cache_for_provider(provider)
    # Invalidate this user's cached catalog response so the new "ready" flag
    # for the just-configured provider shows up on the next /catalog GET.
    # NOTE: we do NOT touch the 24h discovery cache (model_catalog:v3:*).
    # That cache is global because the vendor's /v1/models response is the
    # same for every key — rotating one user's key doesn't change which
    # models the vendor advertises. The per-user "ready"/"selected_for"
    # bits are recomputed every catalog read, sourced from this user's
    # api-key DB row at that moment.
    await invalidate(f"models:catalog:{current_user.username}")
    return {"status": "saved", **result}


@router.delete("/models/api-keys/{provider}")
async def delete_my_api_key(
    provider: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.cache_service import invalidate
    from app.services.user_api_key_service import delete_user_api_key
    deleted = delete_user_api_key(current_user.username, provider, db=db)
    from app.core.model_registry import clear_llm_cache_for_provider
    clear_llm_cache_for_provider(provider)
    # Per-user 60s catalog wrapper needs to drop so the next /catalog read
    # recomputes "ready" flags from the now-empty key state. The 24h
    # global discovery cache is left alone — see comment in upsert.
    await invalidate(f"models:catalog:{current_user.username}")
    return {"status": "deleted" if deleted else "noop"}


@router.post("/models/ping")
async def ping_models(
    current_user: User = Depends(get_current_user),
):
    """Ping every configured profile in parallel; report which are reachable.

    Used by the Models page refresh button so the user sees a green/red dot
    per profile rather than discovering breakage only when they try to use
    a model in production.
    """
    ids = list(_get_all_profiles().keys())
    results = await asyncio.gather(*[_ping_one(pid, user_id=current_user.username) for pid in ids])
    return {"results": results, "checked_at": int(time.time())}


# ── Per-user provider settings (P6-M) ──────────────────────────────────
#
# These endpoints power the Models page's "show more vendors" picker
# + per-vendor settings dialog. They're separate from the existing
# /models/api-keys because:
#   * Key is a SECRET (encrypted column, never echoed back)
#   * Settings are NON-SECRET configuration (api_base / org_id / enabled)
# Different access patterns + different audit needs → separate tables.


@router.get("/models/providers")
async def api_list_providers(
    current_user: User = Depends(get_current_user),
):
    """List every known provider with the user's effective settings.

    Used by the Models page to render both the enabled vendor cards
    AND the "show more vendors" picker in a single request. The
    response includes ALL providers in ``PROVIDERS`` — the frontend
    decides whether to show or hide each based on ``enabled``.
    """
    from app.services.user_provider_settings_service import (
        resolve_all_provider_settings,
    )
    settings = resolve_all_provider_settings(current_user.username)
    return {
        "status": "success",
        "providers": [s.to_dict() for s in settings],
    }


@router.get("/models/providers/{provider}")
async def api_get_provider_settings(
    provider: str,
    current_user: User = Depends(get_current_user),
):
    """Effective settings for one provider — same shape as one entry
    from the /models/providers list endpoint."""
    from app.services.user_provider_settings_service import (
        resolve_provider_settings,
    )
    resolved = resolve_provider_settings(current_user.username, provider)
    if resolved is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown provider: {provider}",
        )
    return {"status": "success", "provider": resolved.to_dict()}


@router.patch("/models/providers/{provider}")
async def api_update_provider_settings(
    provider: str,
    body: ProviderSettingsUpdateRequest,
    current_user: User = Depends(get_current_user),
):
    """Update the user's per-provider overrides.

    Validation happens in the Pydantic field validators above:
      * api_base_override → SSRF guard + HTTPS-only + length cap
      * organization_id   → control-char + length cap
      * extra_headers_json → JSON-object shape + reserved-name blocklist

    The 60-s catalog wrapper for this user is invalidated so the
    next /catalog read reflects any new ``enabled`` state. The LLM
    client cache for the provider is cleared so the next chat call
    rebuilds with the new api_base / headers.
    """
    from app.services.cache_service import invalidate
    from app.services.user_provider_settings_service import (
        SettingsPatch, upsert_settings,
    )

    patch = SettingsPatch(
        enabled=body.enabled,
        api_base_override=body.api_base_override,
        organization_id=body.organization_id,
        extra_headers_json=body.extra_headers_json,
    )

    try:
        resolved = upsert_settings(current_user.username, provider, patch)
    except ValueError as exc:
        # Unknown provider.
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    # Tear down cached clients so the next chat reads the new api_base
    # / extra_headers. clear_llm_cache_for_provider drops both the
    # LlamaIndex LLM cache and the AsyncOpenAI client pool.
    from app.core.model_registry import clear_llm_cache_for_provider
    clear_llm_cache_for_provider(provider)
    await invalidate(f"models:catalog:{current_user.username}")
    return {"status": "saved", "provider": resolved.to_dict()}


@router.delete("/models/providers/{provider}")
async def api_delete_provider_settings(
    provider: str,
    current_user: User = Depends(get_current_user),
):
    """Delete the user's override row, reverting to provider defaults.

    Does NOT remove the user's encrypted API key for that provider —
    use ``DELETE /models/api-keys/{provider}`` for that.
    """
    from app.services.cache_service import invalidate
    from app.services.user_provider_settings_service import delete_settings

    deleted = delete_settings(current_user.username, provider)

    # Cached LLM clients embed the old api_base in their fingerprint,
    # so drop them whether or not a row was present (cheap no-op if
    # there were no entries).
    from app.core.model_registry import clear_llm_cache_for_provider
    clear_llm_cache_for_provider(provider)
    await invalidate(f"models:catalog:{current_user.username}")
    return {"status": "deleted" if deleted else "noop"}


@router.put("/models/runtime")
async def api_update_model_runtime(
    request: RuntimeSelectionUpdateRequest,
    current_user: User = Depends(get_current_user),
):
    updates = {
        role: value
        for role, value in request.model_dump().items()
        if value is not None
    }
    if not updates:
        raise HTTPException(status_code=400, detail="No model role update provided")

    from app.services.cache_service import invalidate
    try:
        for role, profile_id in updates.items():
            validate_role_update(role, profile_id, user_id=current_user.username)
        selection = update_runtime_selection(updates, user_id=current_user.username)
        refresh_primary_llm()
        # The selection affects every profile's `selected_for` in the cached
        # catalog payload, so drop it for this user.
        await invalidate(f"models:catalog:{current_user.username}")
        return {
            "status": "success",
            "selection": selection,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to update runtime model selection: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
