"""Authenticated PersistentTask definition and manual-trigger boundary."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TypeVar

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.agent_runtime.turn_tool_catalog import (
    cloud_sustainable_automation_tool_names,
)
from app.agent_runtime.tool_registry import registry
from app.core.security import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.schemas.persistent_task import (
    PersistentTaskCreate,
    PersistentTaskDelete,
    PersistentTaskDeletionImpact,
    PersistentTaskEligibleToolView,
    PersistentTaskStateChange,
    PersistentTaskTriggerAdmissionView,
    PersistentTaskTriggerInput,
    PersistentTaskTriggerView,
    PersistentTaskUpdate,
    PersistentTaskView,
)
from app.services import persistent_task_service
from app.services.chat.turn_executor import schedule_turn


router = APIRouter(prefix="/persistent-tasks", tags=["persistent-tasks"])
logger = logging.getLogger(__name__)
_T = TypeVar("_T")


def _domain_http_error(
    exc: persistent_task_service.PersistentTaskError,
) -> HTTPException:
    if isinstance(exc, persistent_task_service.PersistentTaskNotFoundError):
        return HTTPException(status_code=404, detail="PersistentTask not found")
    if isinstance(exc, persistent_task_service.PersistentTaskToolScopeError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(
        exc,
        (
            persistent_task_service.PersistentTaskIdempotencyConflictError,
            persistent_task_service.PersistentTaskPausedError,
            persistent_task_service.PersistentTaskTriggerConflictError,
            persistent_task_service.PersistentTaskVersionConflictError,
            persistent_task_service.PersistentTaskDeleteConflictError,
        ),
    ):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


def _run_domain(
    db: Session,
    operation: Callable[[], _T],
    *,
    commit: bool = False,
) -> _T:
    try:
        result = operation()
        if commit:
            db.commit()
        return result
    except persistent_task_service.PersistentTaskError as exc:
        if commit:
            db.rollback()
        raise _domain_http_error(exc) from exc
    except Exception:
        if commit:
            db.rollback()
        raise


@router.get("", response_model=list[PersistentTaskView])
def get_persistent_tasks(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return persistent_task_service.list_persistent_tasks(
        db,
        user_pk=current_user.id,
    )


@router.post("", response_model=PersistentTaskView, status_code=status.HTTP_201_CREATED)
def post_persistent_task(
    body: PersistentTaskCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _run_domain(
        db,
        lambda: persistent_task_service.create_persistent_task(
            db,
            user_pk=current_user.id,
            command=body,
            cloud_sustainable_tool_names=cloud_sustainable_automation_tool_names(),
        ),
        commit=True,
    )


@router.get(
    "/eligible-tools",
    response_model=list[PersistentTaskEligibleToolView],
)
def get_persistent_task_eligible_tools(
    current_user: User = Depends(get_current_user),
):
    """Project the current real catalog; the frontend never owns this list."""

    eligible_names = cloud_sustainable_automation_tool_names()
    snapshot = registry.snapshot(user_id=current_user.username)
    return [
        PersistentTaskEligibleToolView(
            name=name,
            description=snapshot.entries[name].description,
        )
        for name in sorted(eligible_names.intersection(snapshot.entries))
    ]


@router.get("/{task_id}", response_model=PersistentTaskView)
def get_persistent_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _run_domain(
        db,
        lambda: persistent_task_service.get_persistent_task(
            db,
            user_pk=current_user.id,
            task_id=task_id,
        ),
    )


@router.get(
    "/{task_id}/triggers",
    response_model=list[PersistentTaskTriggerView],
)
def get_persistent_task_triggers(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _run_domain(
        db,
        lambda: persistent_task_service.list_persistent_task_triggers(
            db,
            user_pk=current_user.id,
            task_id=task_id,
        ),
    )


@router.patch("/{task_id}", response_model=PersistentTaskView)
def patch_persistent_task(
    task_id: str,
    body: PersistentTaskUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _run_domain(
        db,
        lambda: persistent_task_service.update_persistent_task(
            db,
            user_pk=current_user.id,
            task_id=task_id,
            command=body,
            cloud_sustainable_tool_names=cloud_sustainable_automation_tool_names(),
        ),
        commit=True,
    )


@router.delete("/{task_id}")
def delete_persistent_task(
    task_id: str,
    body: PersistentTaskDelete,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = _run_domain(
        db,
        lambda: persistent_task_service.delete_persistent_task(
            db,
            user_pk=current_user.id,
            task_id=task_id,
            command=body,
        ),
        commit=True,
    )
    from app.task_queue.dispatch import revoke_task

    for ingestion_task_id in result.ingestion_task_ids:
        try:
            revoke_task(ingestion_task_id)
        except Exception:  # noqa: BLE001 - cleanup is already durable
            logger.warning(
                "Could not revoke deleted attachment ingestion task %s",
                ingestion_task_id,
                exc_info=True,
            )
    if result.cancelled_turn_id:
        try:
            from app.core.async_runtime import run_async
            from app.services.chat.turn_event_buffer import turn_event_buffer

            run_async(turn_event_buffer.request_cancel(result.cancelled_turn_id))
        except Exception:  # noqa: BLE001 - DB dispatch fence is authoritative
            logger.warning(
                "Could not signal deleted PersistentTask Turn %s",
                result.cancelled_turn_id,
                exc_info=True,
            )
    return {
        "status": "success",
        "id": result.task_id,
        "receipt_tombstones": result.receipt_tombstones,
    }


@router.get(
    "/{task_id}/deletion-impact",
    response_model=PersistentTaskDeletionImpact,
)
def get_persistent_task_deletion_impact(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _run_domain(
        db,
        lambda: persistent_task_service.preview_persistent_task_deletion(
            db,
            user_pk=current_user.id,
            task_id=task_id,
        ),
    )


def _change_state(
    db: Session,
    *,
    user_pk: int,
    task_id: str,
    body: PersistentTaskStateChange,
    expected_state: str,
):
    if body.state != expected_state:
        raise HTTPException(
            status_code=422,
            detail=f"This endpoint requires state={expected_state}",
        )
    return _run_domain(
        db,
        lambda: persistent_task_service.change_persistent_task_state(
            db,
            user_pk=user_pk,
            task_id=task_id,
            command=body,
        ),
        commit=True,
    )


@router.post("/{task_id}/pause", response_model=PersistentTaskView)
def pause_persistent_task(
    task_id: str,
    body: PersistentTaskStateChange,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _change_state(
        db,
        user_pk=current_user.id,
        task_id=task_id,
        body=body,
        expected_state="paused",
    )


@router.post("/{task_id}/resume", response_model=PersistentTaskView)
def resume_persistent_task(
    task_id: str,
    body: PersistentTaskStateChange,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _change_state(
        db,
        user_pk=current_user.id,
        task_id=task_id,
        body=body,
        expected_state="active",
    )


@router.post(
    "/{task_id}/trigger",
    response_model=PersistentTaskTriggerAdmissionView,
    status_code=status.HTTP_202_ACCEPTED,
)
def trigger_persistent_task(
    task_id: str,
    body: PersistentTaskTriggerInput,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    admission = _run_domain(
        db,
        lambda: persistent_task_service.create_user_confirmed_manual_trigger(
            db,
            user_pk=current_user.id,
            task_id=task_id,
            command=body,
            cloud_sustainable_tool_names=cloud_sustainable_automation_tool_names(),
        ),
        commit=True,
    )
    dispatch_deferred = False
    if admission.should_dispatch and admission.run_request is not None:
        try:
            persistent_task_service.dispatch_automation_run(
                admission,
                lambda request: schedule_turn(request.turn_id),
            )
        except Exception:  # noqa: BLE001 - durable repair owns broker outages
            dispatch_deferred = True
            logger.exception(
                "PersistentTask Turn dispatch deferred to repair: %s",
                admission.turn_id,
            )
    if admission.status == "already_admitted":
        response.status_code = status.HTTP_200_OK
    return PersistentTaskTriggerAdmissionView(
        trigger_id=admission.trigger_id,
        status=admission.status,
        reason="dispatch_deferred" if dispatch_deferred else admission.reason,
        turn_id=admission.turn_id,
        merged_trigger_ids=list(admission.merged_trigger_ids),
        pending_trigger_count=admission.pending_trigger_count,
    )


__all__ = ["cloud_sustainable_automation_tool_names", "router"]
