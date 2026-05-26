import asyncio
import logging
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.core.model_registry import (
    MODEL_PROFILES,
    get_async_openai_client,
    get_profile,
    get_profile_for_role,
    get_runtime_selection,
    list_profiles_with_discovery,
    profile_ready,
    update_runtime_selection,
    validate_role_update,
)
from app.rag.embeddings import refresh_primary_llm

logger = logging.getLogger(__name__)

router = APIRouter(tags=["models"])


class RuntimeSelectionUpdateRequest(BaseModel):
    primary: str | None = Field(default=None, description="Primary LLM profile id")
    fast: str | None = Field(default=None, description="(internal) fast utility LLM, kept for back-compat")
    agent: str | None = Field(default=None, description="Function-calling agent profile id")
    mock_interview: str | None = Field(default=None, description="Mock-interview plan / interviewer LLM")


class APIKeyUpsertRequest(BaseModel):
    api_key: str = Field(..., min_length=4, description="Provider API key. Encrypted at rest; never echoed back.")


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
        # list_profiles_with_discovery merges curated MODEL_PROFILES with
        # whatever each vendor's /v1/models endpoint currently advertises.
        # Discovery itself is cached 24h in Redis (model_catalog_service);
        # this 60-s wrapper just reduces per-page-load DB churn.
        profiles = await list_profiles_with_discovery(user_id=current_user.username)
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
    """Force-refresh the auto-discovered model list for every vendor.

    Drops the per-vendor 24h Redis cache from ``model_catalog_service``
    AND the per-user 60-s catalog cache, then re-runs discovery in the
    same call so the response already reflects the new state.
    """
    from app.services.cache_service import invalidate
    from app.services.model_catalog_service import invalidate_all

    dropped = await invalidate_all()
    await invalidate(f"models:catalog:{current_user.username}")
    profiles = await list_profiles_with_discovery(
        user_id=current_user.username, force_refresh=True,
    )
    auto = sum(1 for p in profiles if p.get("auto_discovered"))
    return {
        "status": "refreshed",
        "discovery_cache_dropped": dropped,
        "profiles_total": len(profiles),
        "profiles_auto_discovered": auto,
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
    ids = list(MODEL_PROFILES.keys())
    results = await asyncio.gather(*[_ping_one(pid, user_id=current_user.username) for pid in ids])
    return {"results": results, "checked_at": int(time.time())}


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
