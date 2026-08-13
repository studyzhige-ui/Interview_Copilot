"""Authenticated exact Interaction History Search."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.schemas.history_search import (
    HistoryRecordDetail,
    HistorySearchQuery,
    HistorySearchResponse,
)
from app.services.interaction_history_service import (
    HistorySearchNotFoundError,
    get_interaction_history_record,
    search_interaction_history,
)

router = APIRouter(prefix="/history", tags=["history"])


@router.get("/search", response_model=HistorySearchResponse)
def search_history(
    query: str = Query(..., min_length=2, max_length=200),
    conversation_id: str | None = None,
    kind: list[Literal["message", "tool_call"]] = Query(default=[]),
    role: list[Literal["user", "assistant", "tool", "system"]] = Query(default=[]),
    limit: int = Query(20, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        request = HistorySearchQuery(
            query=query,
            conversation_id=conversation_id,
            kinds=kind or ["message", "tool_call"],
            roles=role,
            limit=limit,
        )
        return search_interaction_history(db, user_pk=current_user.id, request=request)
    except HistorySearchNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/records/{identity:path}", response_model=HistoryRecordDetail)
def read_history_record(
    identity: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return get_interaction_history_record(
            db,
            user_pk=current_user.id,
            identity=identity,
        )
    except HistorySearchNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


__all__ = ["router"]
