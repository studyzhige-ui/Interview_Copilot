"""Authenticated delivery endpoints for the fixed Mock Client Action handler."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.core.user_identity import resolve_user_pk
from app.db.database import get_db
from app.models.conversation_turn import ConversationTurn
from app.models.user import User
from app.schemas.client_action import (
    MockClientActionResolutionResponse,
    MockClientActionResultRequest,
    MockClientActionTakeoverRequest,
    MockClientActionView,
)
from app.services.chat.client_action_service import (
    ClientActionConflictError,
    ClientActionNotFoundError,
    pending_action_for_client,
    resolve_pending_action,
    takeover_pending_action,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["client-actions"])


@router.get(
    "/chat/{session_id}/turns/{turn_id}/client-actions/pending",
    response_model=MockClientActionView | None,
)
def get_pending_client_action(
    session_id: str,
    turn_id: str,
    client_id: str = Query(min_length=1, max_length=128),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Replay a pending action only to the instance currently bound to it."""

    user_pk = resolve_user_pk(db, current_user.username)
    try:
        return pending_action_for_client(
            db,
            session_id=session_id,
            turn_id=turn_id,
            user_id=user_pk,
            client_id=client_id,
        )
    except ClientActionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/chat/{session_id}/turns/{turn_id}/client-actions/{interaction_id}/takeover",
    response_model=MockClientActionView,
)
def takeover_client_action(
    session_id: str,
    turn_id: str,
    interaction_id: str,
    body: MockClientActionTakeoverRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Explicit user command to bind a stranded action to this client."""

    user_pk = resolve_user_pk(db, current_user.username)
    try:
        row, _replayed = takeover_pending_action(
            db,
            session_id=session_id,
            turn_id=turn_id,
            interaction_id=interaction_id,
            user_id=user_pk,
            action_id=body.action_id,
            expected_version=body.expected_version,
            client_id=body.client_id,
        )
        db.commit()
        view = pending_action_for_client(
            db,
            session_id=session_id,
            turn_id=turn_id,
            user_id=user_pk,
            client_id=body.client_id,
        )
    except ClientActionNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ClientActionConflictError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if view is None or view.interaction_id != row.id:  # pragma: no cover - CAS guard
        raise HTTPException(
            status_code=409, detail="Client Action is no longer pending"
        )
    return view


@router.post(
    "/chat/{session_id}/turns/{turn_id}/client-actions/{interaction_id}/resolve",
    response_model=MockClientActionResolutionResponse,
)
async def resolve_client_action(
    session_id: str,
    turn_id: str,
    interaction_id: str,
    body: MockClientActionResultRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Persist ack/refusal/failure and resume the same Turn/Tool Call once."""

    from app.services.chat.turn_event_buffer import turn_event_buffer
    from app.services.chat.turn_executor import (
        fail_pending_turn,
        resume_waiting_turn,
        schedule_turn,
    )

    user_pk = resolve_user_pk(db, current_user.username)
    try:
        result = resolve_pending_action(
            db,
            session_id=session_id,
            turn_id=turn_id,
            interaction_id=interaction_id,
            user_id=user_pk,
            result=body,
        )
    except ClientActionNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ClientActionConflictError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if result.replayed:
        turn = db.get(ConversationTurn, turn_id)
        if turn is None:  # pragma: no cover - owning service already checked
            raise HTTPException(status_code=404, detail="Turn not found")
        return MockClientActionResolutionResponse(
            action_id=body.action_id,
            interaction_id=result.interaction.id,
            replayed=True,
            turn_status=turn.status,
            dispatch_generation=int(turn.dispatch_generation or 1),
        )

    generation = resume_waiting_turn(
        db,
        turn_id,
        user_pk,
        expected_reason="interaction",
    )
    if generation is None:
        db.rollback()
        raise HTTPException(status_code=409, detail="Turn is not waiting")
    try:
        await turn_event_buffer.reset(turn_id)
        schedule_turn(turn_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Could not resume Client Action Turn %s", turn_id)
        fail_pending_turn(db, turn_id, user_pk, "后台任务队列暂时不可用")
        raise HTTPException(status_code=503, detail="无法恢复本轮执行") from exc
    return MockClientActionResolutionResponse(
        action_id=body.action_id,
        interaction_id=result.interaction.id,
        replayed=False,
        turn_status="pending",
        dispatch_generation=generation,
    )


__all__ = ["router"]
