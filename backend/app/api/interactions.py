"""User-level Interaction queries for Today and other product projections."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.schemas.agent_interaction import (
    AgentInteractionView,
    PendingInteractionProjection,
)
from app.services.chat.interaction_service import list_pending_interactions


router = APIRouter(prefix="/interactions", tags=["interactions"])


@router.get("/pending-confirmations", response_model=list[PendingInteractionProjection])
def pending_confirmations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[PendingInteractionProjection]:
    """Project only the three Interaction kinds allowed in Today confirmation."""

    rows = list_pending_interactions(
        db,
        user_id=current_user.id,
        kinds=("approval", "fact_confirmation", "profile_update_confirmation"),
    )
    return [
        PendingInteractionProjection(
            conversation_id=turn.conversation_id,
            turn_status=turn.status,
            interaction=AgentInteractionView.model_validate(interaction),
        )
        for interaction, turn in rows
    ]


__all__ = ["router"]
