import asyncio
import logging
import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.security import get_current_user
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
from app.schemas.model_runtime import (
    APIKeyUpsertRequest,
    ProviderSettingsUpdateRequest,
    RuntimeSelectionUpdateRequest,
)
from app.services.model_sources.pipeline import load_catalog, refresh_catalog

logger = logging.getLogger(__name__)

router = APIRouter(tags=["models"])


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
        # Pull the catalog from the Redis pipeline cache. ``load_catalog``
        # doesn't hit any vendor — that's the daily Celery beat's job
        # plus the manual refresh-catalog endpoint below. The
        # serialization layer joins each ``ModelEntry`` with its
        # ``ProviderDefaults`` and tags per-user state (ready /
        # selected_for).
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
    """Force-refresh the model catalog from every vendor.

    ``refresh_catalog`` fans out to each vendor's /v1/models in parallel,
    applies per-vendor chat filters + curated UX layer, then persists
    per-provider entries to Redis. Per-vendor failure is isolated —
    one vendor down doesn't blank the others, that vendor's slice
    falls back to its last-known-good snapshot. The user's 60-s
    catalog wrapper is invalidated so this user sees fresh entries
    on their very next read.
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
    from app.services.auth.user_api_key_service import list_user_api_keys
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
    from app.services.auth.user_api_key_service import set_user_api_key
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
    from app.services.auth.user_api_key_service import delete_user_api_key
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
    from app.services.auth.user_provider_settings_service import (
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
    from app.services.auth.user_provider_settings_service import (
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
    from app.services.auth.user_provider_settings_service import (
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
    from app.services.auth.user_provider_settings_service import delete_settings

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
