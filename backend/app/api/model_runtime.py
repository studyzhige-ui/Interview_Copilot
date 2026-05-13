import asyncio
import logging
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.security import get_current_user
from app.models.user import User
from app.core.model_registry import (
    MODEL_PROFILES,
    get_profile,
    get_profile_for_role,
    get_runtime_selection,
    list_profiles,
    profile_ready,
    resolve_api_key,
    update_runtime_selection,
    validate_role_update,
)
from app.rag.embeddings import refresh_primary_llm

logger = logging.getLogger(__name__)

router = APIRouter(tags=["models"])


class RuntimeSelectionUpdateRequest(BaseModel):
    primary: str | None = Field(default=None, description="Primary LLM profile id")
    fast: str | None = Field(default=None, description="Fast utility LLM profile id")
    agent: str | None = Field(default=None, description="Function-calling agent profile id")


@router.get("/models/catalog")
async def api_model_catalog(
    current_user: User = Depends(get_current_user),
):
    selection = get_runtime_selection()
    return {
        "status": "success",
        "selection": selection,
        "profiles": list_profiles(),
    }


@router.get("/models/runtime")
async def api_model_runtime(
    current_user: User = Depends(get_current_user),
):
    selection = get_runtime_selection()
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
                "primary": get_profile_for_role("primary"),
                "fast": get_profile_for_role("fast"),
                "agent": get_profile_for_role("agent"),
            }.items()
        },
    }


async def _ping_one(profile_id: str) -> dict:
    """Issue a minimal completion to check the provider/key is reachable.

    Returns ``{profile_id, ok, latency_ms, error?}``. Never raises.
    """
    started = time.perf_counter()
    try:
        profile = get_profile(profile_id)
    except ValueError as exc:
        return {"profile_id": profile_id, "ok": False, "latency_ms": 0, "error": str(exc)}
    if not profile_ready(profile):
        return {
            "profile_id": profile_id, "ok": False, "latency_ms": 0,
            "error": f"未配置 {profile.api_key_env}",
        }

    from openai import AsyncOpenAI
    try:
        client = AsyncOpenAI(api_key=resolve_api_key(profile), base_url=profile.api_base, timeout=8.0)
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
    results = await asyncio.gather(*[_ping_one(pid) for pid in ids])
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

    try:
        for role, profile_id in updates.items():
            validate_role_update(role, profile_id)
        selection = update_runtime_selection(updates)
        refresh_primary_llm()
        return {
            "status": "success",
            "selection": selection,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to update runtime model selection: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
