"""Authenticated HTTP boundary for the Stage 2 career-process slice.

The router is intentionally thin: product writes go through the same
``career_process_service`` commands used by future Agent tools and connector
handlers.  This public boundary can author user assertions and can reference
an owned, active ProcessEvent.  It cannot manufacture Observation, ToolResult,
receipt, Agent suggestion, or CopilotPreference identities; those source kinds
must enter through the concrete trusted handler that owns and validates them.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.schemas.job_opportunity import (
    JobOpportunityView,
    NextActionClose,
    NextActionCreate,
    NextActionEdit,
    NextActionStatus,
    NextActionTransition,
    NextActionView,
    OpportunityCreate,
    OpportunityDirectionsReplace,
    OpportunityMergeCandidateView,
    OpportunityMergeCreate,
    OpportunityMergeRetract,
    OpportunityMergeView,
    ProcessEventAppend,
    ProcessEventCorrection,
    ProcessEventView,
)
from app.schemas.job_description_snapshot import (
    JobDescriptionSnapshotFromProductUI,
    JobDescriptionSnapshotView,
)
from app.services.job_description_snapshot_service import (
    JobDescriptionSnapshotError,
    create_job_description_snapshot,
    list_job_description_snapshots,
)
from app.services.career_process_service import (
    CareerIdempotencyConflictError,
    CareerObjectNotFoundError,
    CareerProcessError,
    NextActionTransitionError,
    OpportunityArchivedError,
    OpportunityDirectionConflictError,
    OpportunityMergeConflictError,
    ProcessEventConflictError,
    append_confirmed_process_event,
    close_next_action,
    complete_next_action,
    correct_process_event,
    create_job_opportunity,
    create_next_action,
    edit_next_action,
    list_job_opportunities,
    list_opportunity_merges,
    list_next_actions,
    list_process_events,
    plan_next_action,
    merge_job_opportunities,
    retract_job_opportunity_merge,
    replace_job_opportunity_directions,
    suggest_opportunity_merge_candidates,
)


router = APIRouter(prefix="/career-process", tags=["career-process"])

_T = TypeVar("_T")


def _domain_http_error(exc: CareerProcessError) -> HTTPException:
    if isinstance(exc, CareerObjectNotFoundError):
        return HTTPException(status_code=404, detail="Career process object not found")
    if isinstance(
        exc,
        (
            CareerIdempotencyConflictError,
            NextActionTransitionError,
            OpportunityArchivedError,
            OpportunityDirectionConflictError,
            OpportunityMergeConflictError,
            ProcessEventConflictError,
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
    except CareerProcessError as exc:
        if commit:
            db.rollback()
        raise _domain_http_error(exc) from exc
    except Exception:
        if commit:
            db.rollback()
        raise


def _require_user_assertion(source_kind: str) -> None:
    if source_kind != "user_assertion":
        raise HTTPException(
            status_code=422,
            detail=(
                "This authenticated endpoint only accepts user_assertion sources; "
                "Observation, ToolResult, and receipt sources require their trusted "
                "internal handler"
            ),
        )


def _require_direct_action_source(source_kind: str) -> None:
    if source_kind not in {"user_request", "process_event"}:
        raise HTTPException(
            status_code=422,
            detail=(
                "This endpoint only accepts user_request or an owned active "
                "process_event source"
            ),
        )


def _require_direct_transition_source(
    source_kind: str,
    *,
    allow_process_event: bool,
) -> None:
    allowed = {"user_assertion"}
    if allow_process_event:
        allowed.add("process_event")
    if source_kind not in allowed:
        raise HTTPException(
            status_code=422,
            detail=(
                "This endpoint cannot accept an unverified ToolResult, application "
                "result, or CopilotPreference source"
            ),
        )


@router.get("/opportunities", response_model=list[JobOpportunityView])
def get_opportunities(
    include_archived: bool = False,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_job_opportunities(
        db,
        user_pk=current_user.id,
        include_archived=include_archived,
        limit=limit,
        offset=offset,
    )


@router.post("/opportunities", response_model=JobOpportunityView)
def post_opportunity(
    payload: OpportunityCreate,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_user_assertion(payload.source_kind)
    if payload.entry_reason == "verified_submission":
        raise HTTPException(
            status_code=422,
            detail=(
                "verified_submission requires a trusted receipt/ToolResult handler; "
                "use user_confirmed_application for a user assertion"
            ),
        )
    admission = _run_domain(
        db,
        lambda: create_job_opportunity(
            db,
            user_pk=current_user.id,
            command=payload,
        ),
        commit=True,
    )
    response.status_code = (
        status.HTTP_201_CREATED if admission.created else status.HTTP_200_OK
    )
    return admission.opportunity


@router.get(
    "/opportunity-merge-candidates",
    response_model=list[OpportunityMergeCandidateView],
)
def get_opportunity_merge_candidates(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return suggest_opportunity_merge_candidates(db, user_pk=current_user.id)


@router.get("/opportunity-merges", response_model=list[OpportunityMergeView])
def get_opportunity_merges(
    include_retracted: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_opportunity_merges(
        db,
        user_pk=current_user.id,
        include_retracted=include_retracted,
    )


@router.get(
    "/opportunities/{opportunity_id}/jd-snapshots",
    response_model=list[JobDescriptionSnapshotView],
)
def read_job_description_snapshots(
    opportunity_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[JobDescriptionSnapshotView]:
    try:
        rows = list_job_description_snapshots(
            db,
            user_pk=current_user.id,
            opportunity_id=opportunity_id,
        )
    except JobDescriptionSnapshotError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [JobDescriptionSnapshotView.model_validate(row) for row in rows]


@router.post(
    "/opportunities/{opportunity_id}/jd-snapshots",
    response_model=JobDescriptionSnapshotView,
    status_code=status.HTTP_201_CREATED,
)
def create_product_ui_job_description_snapshot(
    opportunity_id: str,
    command: JobDescriptionSnapshotFromProductUI,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> JobDescriptionSnapshotView:
    """Persist an explicit typed product-UI JD submission."""

    try:
        row = create_job_description_snapshot(
            db,
            user_pk=current_user.id,
            opportunity_id=opportunity_id,
            command=command,
        )
        db.commit()
        db.refresh(row)
    except JobDescriptionSnapshotError as exc:
        db.rollback()
        error_name = type(exc).__name__
        status_code = 404 if error_name.endswith("NotFound") else 422
        if error_name.endswith("IdempotencyConflict"):
            status_code = 409
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return JobDescriptionSnapshotView.model_validate(row)


@router.post(
    "/opportunity-merges",
    response_model=OpportunityMergeView,
    status_code=status.HTTP_201_CREATED,
)
def post_opportunity_merge(
    payload: OpportunityMergeCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _run_domain(
        db,
        lambda: merge_job_opportunities(db, user_pk=current_user.id, command=payload),
        commit=True,
    )


@router.post(
    "/opportunity-merges/{merge_id}/retract",
    response_model=OpportunityMergeView,
)
def post_opportunity_merge_retraction(
    merge_id: str,
    payload: OpportunityMergeRetract,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _run_domain(
        db,
        lambda: retract_job_opportunity_merge(
            db,
            user_pk=current_user.id,
            merge_id=merge_id,
            command=payload,
        ),
        commit=True,
    )


@router.patch(
    "/opportunities/{opportunity_id}/directions",
    response_model=JobOpportunityView,
)
def patch_opportunity_directions(
    opportunity_id: str,
    payload: OpportunityDirectionsReplace,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_user_assertion(payload.source_kind)
    return _run_domain(
        db,
        lambda: replace_job_opportunity_directions(
            db,
            user_pk=current_user.id,
            opportunity_id=opportunity_id,
            command=payload,
        ),
        commit=True,
    )


@router.get(
    "/opportunities/{opportunity_id}/events",
    response_model=list[ProcessEventView],
)
def get_process_events(
    opportunity_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _run_domain(
        db,
        lambda: list_process_events(
            db,
            user_pk=current_user.id,
            opportunity_id=opportunity_id,
        ),
    )


@router.post(
    "/opportunities/{opportunity_id}/events",
    response_model=ProcessEventView,
    status_code=status.HTTP_201_CREATED,
)
def post_confirmed_process_event(
    opportunity_id: str,
    payload: ProcessEventAppend,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_user_assertion(payload.source_kind)
    return _run_domain(
        db,
        lambda: append_confirmed_process_event(
            db,
            user_pk=current_user.id,
            opportunity_id=opportunity_id,
            command=payload,
        ),
        commit=True,
    )


@router.post(
    "/opportunities/{opportunity_id}/events/{event_id}/corrections",
    response_model=ProcessEventView,
    status_code=status.HTTP_201_CREATED,
)
def post_process_event_correction(
    opportunity_id: str,
    event_id: str,
    payload: ProcessEventCorrection,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_user_assertion(payload.source_kind)
    return _run_domain(
        db,
        lambda: correct_process_event(
            db,
            user_pk=current_user.id,
            opportunity_id=opportunity_id,
            target_event_id=event_id,
            command=payload,
        ),
        commit=True,
    )


@router.get("/next-actions", response_model=list[NextActionView])
def get_next_actions(
    statuses: list[NextActionStatus] | None = Query(default=None),
    limit: int = Query(200, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_next_actions(
        db,
        user_pk=current_user.id,
        statuses=set(statuses) if statuses else None,
        limit=limit,
    )


@router.post(
    "/next-actions",
    response_model=NextActionView,
    status_code=status.HTTP_201_CREATED,
)
def post_next_action(
    payload: NextActionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_direct_action_source(payload.source_kind)
    return _run_domain(
        db,
        lambda: create_next_action(
            db,
            user_pk=current_user.id,
            command=payload,
        ),
        commit=True,
    )


@router.put("/next-actions/{action_id}", response_model=NextActionView)
def put_next_action(
    action_id: str,
    payload: NextActionEdit,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _run_domain(
        db,
        lambda: edit_next_action(
            db,
            user_pk=current_user.id,
            action_id=action_id,
            command=payload,
        ),
        commit=True,
    )


@router.post("/next-actions/{action_id}/plan", response_model=NextActionView)
def post_next_action_plan(
    action_id: str,
    payload: NextActionTransition,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_direct_transition_source(
        payload.source_kind,
        allow_process_event=False,
    )
    return _run_domain(
        db,
        lambda: plan_next_action(
            db,
            user_pk=current_user.id,
            action_id=action_id,
            transition=payload,
        ),
        commit=True,
    )


@router.post("/next-actions/{action_id}/complete", response_model=NextActionView)
def post_next_action_complete(
    action_id: str,
    payload: NextActionTransition,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_direct_transition_source(
        payload.source_kind,
        allow_process_event=True,
    )
    return _run_domain(
        db,
        lambda: complete_next_action(
            db,
            user_pk=current_user.id,
            action_id=action_id,
            transition=payload,
        ),
        commit=True,
    )


@router.post("/next-actions/{action_id}/close", response_model=NextActionView)
def post_next_action_close(
    action_id: str,
    payload: NextActionClose,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_direct_transition_source(
        payload.source_kind,
        allow_process_event=True,
    )
    return _run_domain(
        db,
        lambda: close_next_action(
            db,
            user_pk=current_user.id,
            action_id=action_id,
            transition=payload,
        ),
        commit=True,
    )


__all__ = ["router"]
