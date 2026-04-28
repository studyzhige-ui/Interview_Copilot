import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.security import get_current_user
from app.models.user import User
from app.core.model_registry import (
    get_profile_for_role,
    get_runtime_selection,
    list_profiles,
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
