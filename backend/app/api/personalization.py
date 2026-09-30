"""Explicit personalization commands; each lifetime keeps its real owner."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.schemas.agent_memory import (
    AgentMemoryPromotionCommand,
    AgentMemoryPromotionView,
    AgentMemorySettingsUpdate,
    AgentMemorySettingsView,
    AgentMemoryStatusCommand,
    AgentMemoryUpdate,
    AgentMemoryView,
    ConversationMemoryControlsUpdate,
    ConversationMemoryControlsView,
    MemoryFeedbackCommand,
)
from app.schemas.personalization import (
    CopilotPreferenceUpdate,
    CopilotPreferenceView,
    ScopedGuidanceUpdate,
    ScopedGuidanceView,
)
from app.memory import lifecycle as agent_memory_service
from app.career.application import personalization as personalization_service


router = APIRouter(prefix="/personalization", tags=["personalization"])


@router.get("/memory-pipeline")
def memory_pipeline_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from sqlalchemy import func
    from app.models.memory_pipeline import MemoryExtraction, MemoryWorkspace
    from app.core.config import settings

    counts = (
        db.query(MemoryExtraction.status, func.count())
        .filter(MemoryExtraction.user_id == current_user.id)
        .group_by(MemoryExtraction.status)
        .all()
    )
    workspace = db.get(MemoryWorkspace, current_user.id)
    return {
        "producer_available": settings.AGENT_MEMORY_PRODUCER_ENABLED,
        "extractions": dict(counts),
        "consolidation": {
            "status": workspace.status,
            "revision": workspace.revision,
            "error_code": workspace.error_code,
            "retry_at": workspace.retry_at,
            "updated_at": workspace.updated_at,
        }
        if workspace
        else None,
    }


@router.get("/memory-receipts")
def memory_receipts(
    turn_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.models.memory_pipeline import MemoryReadReceipt

    query = db.query(MemoryReadReceipt).filter(
        MemoryReadReceipt.user_id == current_user.id
    )
    if turn_id:
        query = query.filter(MemoryReadReceipt.turn_id == turn_id)
    return [
        {
            "id": r.id,
            "turn_id": r.turn_id,
            "memory_id": r.memory_id,
            "memory_version": r.memory_version,
            "cited_at": r.cited_at,
            "feedback": r.feedback,
            "created_at": r.created_at,
        }
        for r in query.order_by(MemoryReadReceipt.created_at.desc()).limit(100).all()
    ]


@router.put("/memory-receipts/{receipt_id}/feedback")
def memory_feedback(
    receipt_id: str,
    body: MemoryFeedbackCommand,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.memory.recall import set_feedback

    return _run_memory(
        db,
        lambda: set_feedback(
            db, user_id=current_user.id, receipt_id=receipt_id, feedback=body.feedback
        ),
        commit=True,
    )


def _run(db: Session, operation, *, commit: bool = False):
    try:
        result = operation()
        if commit:
            db.commit()
        return result
    except personalization_service.PersonalizationNotFoundError as exc:
        if commit:
            db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except personalization_service.PersonalizationConflictError as exc:
        if commit:
            db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _run_memory(db: Session, operation, *, commit: bool = False):
    try:
        result = operation()
        if commit:
            db.commit()
        return result
    except agent_memory_service.AgentMemoryNotFoundError as exc:
        if commit:
            db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except agent_memory_service.AgentMemoryConflictError as exc:
        if commit:
            db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/copilot-preference", response_model=CopilotPreferenceView)
def get_copilot_preference(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return personalization_service.get_copilot_preference(db, user_pk=current_user.id)


@router.put("/copilot-preference", response_model=CopilotPreferenceView)
def put_copilot_preference(
    body: CopilotPreferenceUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _run(
        db,
        lambda: personalization_service.replace_copilot_preference(
            db,
            user_pk=current_user.id,
            command=body,
        ),
        commit=True,
    )


@router.get(
    "/conversations/{conversation_id}/guidance",
    response_model=ScopedGuidanceView,
)
def get_conversation_guidance(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _run(
        db,
        lambda: personalization_service.get_conversation_guidance(
            db,
            user_pk=current_user.id,
            conversation_id=conversation_id,
        ),
    )


@router.put(
    "/conversations/{conversation_id}/guidance",
    response_model=ScopedGuidanceView,
)
def put_conversation_guidance(
    conversation_id: str,
    body: ScopedGuidanceUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _run(
        db,
        lambda: personalization_service.update_conversation_guidance(
            db,
            user_pk=current_user.id,
            conversation_id=conversation_id,
            command=body,
        ),
        commit=True,
    )


@router.get(
    "/interviews/{interview_record_id}/guidance",
    response_model=ScopedGuidanceView,
)
def get_debrief_guidance(
    interview_record_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _run(
        db,
        lambda: personalization_service.get_debrief_guidance(
            db,
            user_pk=current_user.id,
            interview_record_id=interview_record_id,
        ),
    )


@router.put(
    "/interviews/{interview_record_id}/guidance",
    response_model=ScopedGuidanceView,
)
def put_debrief_guidance(
    interview_record_id: str,
    body: ScopedGuidanceUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _run(
        db,
        lambda: personalization_service.update_debrief_guidance(
            db,
            user_pk=current_user.id,
            interview_record_id=interview_record_id,
            command=body,
        ),
        commit=True,
    )


@router.get("/memory-settings", response_model=AgentMemorySettingsView)
def get_memory_settings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return agent_memory_service.get_settings(db, user_pk=current_user.id)


@router.put("/memory-settings", response_model=AgentMemorySettingsView)
def put_memory_settings(
    body: AgentMemorySettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _run_memory(
        db,
        lambda: agent_memory_service.update_settings(
            db,
            user_pk=current_user.id,
            command=body,
        ),
        commit=True,
    )


@router.get(
    "/conversations/{conversation_id}/memory-controls",
    response_model=ConversationMemoryControlsView,
)
def get_conversation_memory_controls(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _run_memory(
        db,
        lambda: agent_memory_service.get_conversation_controls(
            db,
            user_pk=current_user.id,
            conversation_id=conversation_id,
        ),
    )


@router.put(
    "/conversations/{conversation_id}/memory-controls",
    response_model=ConversationMemoryControlsView,
)
def put_conversation_memory_controls(
    conversation_id: str,
    body: ConversationMemoryControlsUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _run_memory(
        db,
        lambda: agent_memory_service.update_conversation_controls(
            db,
            user_pk=current_user.id,
            conversation_id=conversation_id,
            command=body,
        ),
        commit=True,
    )


@router.get("/memories", response_model=list[AgentMemoryView])
def get_memories(
    include_inactive: bool = Query(False),
    limit: int = Query(100, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return agent_memory_service.list_memories(
        db,
        user_pk=current_user.id,
        include_inactive=include_inactive,
        limit=limit,
    )


@router.patch("/memories/{memory_id}", response_model=AgentMemoryView)
def patch_memory(
    memory_id: str,
    body: AgentMemoryUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _run_memory(
        db,
        lambda: agent_memory_service.update_memory(
            db,
            user_pk=current_user.id,
            memory_id=memory_id,
            command=body,
        ),
        commit=True,
    )


@router.post("/memories/{memory_id}/invalidate", response_model=AgentMemoryView)
def invalidate_memory(
    memory_id: str,
    body: AgentMemoryStatusCommand,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _run_memory(
        db,
        lambda: agent_memory_service.invalidate_memory(
            db,
            user_pk=current_user.id,
            memory_id=memory_id,
            command=body,
        ),
        commit=True,
    )


@router.delete("/memories/{memory_id}", response_model=AgentMemoryView)
def remove_memory(
    memory_id: str,
    body: AgentMemoryStatusCommand,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _run_memory(
        db,
        lambda: agent_memory_service.delete_memory(
            db,
            user_pk=current_user.id,
            memory_id=memory_id,
            command=body,
        ),
        commit=True,
    )


@router.post(
    "/memories/{memory_id}/promote-to-preference",
    response_model=AgentMemoryPromotionView,
)
def promote_memory_to_preference(
    memory_id: str,
    body: AgentMemoryPromotionCommand,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    memory, preference = _run_memory(
        db,
        lambda: agent_memory_service.promote_memory_to_preference(
            db,
            user_pk=current_user.id,
            memory_id=memory_id,
            command=body,
        ),
        commit=True,
    )
    return AgentMemoryPromotionView(
        memory=memory,
        preference=CopilotPreferenceView(
            id=preference.id,
            instructions=list(preference.instructions_json or []),
            version=int(preference.version),
            updated_at=preference.updated_at,
        ),
    )


__all__ = ["router"]
