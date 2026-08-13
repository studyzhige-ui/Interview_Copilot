"""Authenticated CareerProfile and AbilitySignal product endpoints.

The router is intentionally thin. Confirmed profile writes and inferred
ability lifecycle changes share the same Application Services used by Agent
tools; no second UI-specific state or generic profile/memory layer exists.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.core.user_identity import resolve_user_pk
from app.db.database import get_db
from app.models.user import User
from app.schemas.ability_signal import (
    AbilitySignalRecomputeInput,
    AbilitySignalStatusChangeInput,
    AbilitySignalView,
)
from app.schemas.career_profile import (
    CareerProfileCandidateBatchResolutionInput,
    CareerProfileCandidateResolutionView,
    CareerProfileDraftInput,
    CareerProfileDraftResolutionInput,
    CareerProfileDraftView,
    CareerProfileView,
    DirectionLifecycleMutationInput,
    DirectionMutationInput,
    PersonalFactMutationInput,
    PersonalFactRemovalInput,
)
from app.services import ability_signal_service, career_profile_service

router = APIRouter(tags=["career-profile"])


def _user_pk(db: Session, current_user: User) -> int:
    user_pk = resolve_user_pk(db, current_user.username)
    if user_pk is None:
        raise HTTPException(
            status_code=401, detail="Authenticated user no longer exists"
        )
    return user_pk


def _profile_error(exc: Exception) -> HTTPException:
    if isinstance(exc, career_profile_service.CareerProfileNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, career_profile_service.CareerProfileConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, career_profile_service.CareerProfileOwnershipError):
        return HTTPException(status_code=403, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


def _ability_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ability_signal_service.AbilitySignalNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ability_signal_service.AbilitySignalConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, ability_signal_service.AbilitySignalOwnershipError):
        return HTTPException(status_code=403, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


@router.get("/career-profile", response_model=CareerProfileView)
def read_career_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_pk = _user_pk(db, current_user)
    career_profile_service.ensure_career_profile(db, user_pk=user_pk)
    db.commit()
    return career_profile_service.get_career_profile(db, user_pk=user_pk)


@router.post("/career-profile/facts", response_model=CareerProfileView)
def create_personal_fact(
    body: PersonalFactMutationInput,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        result = career_profile_service.upsert_personal_fact(
            db,
            user_pk=_user_pk(db, current_user),
            expected_profile_version=body.expected_profile_version,
            fact=body.fact,
            confirmation=body.confirmation,
        )
        db.commit()
        return result
    except career_profile_service.CareerProfileError as exc:
        db.rollback()
        raise _profile_error(exc) from exc


@router.put("/career-profile/facts/{fact_id}", response_model=CareerProfileView)
def update_personal_fact(
    fact_id: str,
    body: PersonalFactMutationInput,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        result = career_profile_service.upsert_personal_fact(
            db,
            user_pk=_user_pk(db, current_user),
            expected_profile_version=body.expected_profile_version,
            fact=body.fact,
            confirmation=body.confirmation,
            fact_id=fact_id,
        )
        db.commit()
        return result
    except career_profile_service.CareerProfileError as exc:
        db.rollback()
        raise _profile_error(exc) from exc


@router.delete("/career-profile/facts/{fact_id}", response_model=CareerProfileView)
def delete_personal_fact(
    fact_id: str,
    body: PersonalFactRemovalInput,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        result = career_profile_service.remove_personal_fact(
            db,
            user_pk=_user_pk(db, current_user),
            expected_profile_version=body.expected_profile_version,
            fact_id=fact_id,
            confirmation=body.confirmation,
        )
        db.commit()
        return result
    except career_profile_service.CareerProfileError as exc:
        db.rollback()
        raise _profile_error(exc) from exc


@router.post("/career-profile/directions", response_model=CareerProfileView)
def create_direction(
    body: DirectionMutationInput,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _mutate_direction(None, body, current_user, db)


@router.put(
    "/career-profile/directions/{direction_id}", response_model=CareerProfileView
)
def update_direction(
    direction_id: str,
    body: DirectionMutationInput,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _mutate_direction(direction_id, body, current_user, db)


def _mutate_direction(
    direction_id: str | None,
    body: DirectionMutationInput,
    current_user: User,
    db: Session,
) -> CareerProfileView:
    try:
        result = career_profile_service.upsert_profile_direction(
            db,
            user_pk=_user_pk(db, current_user),
            expected_profile_version=body.expected_profile_version,
            direction=body.direction,
            confirmation=body.confirmation,
            direction_id=direction_id,
        )
        db.commit()
        return result
    except career_profile_service.CareerProfileError as exc:
        db.rollback()
        raise _profile_error(exc) from exc


@router.patch(
    "/career-profile/directions/{direction_id}/lifecycle",
    response_model=CareerProfileView,
)
def update_direction_lifecycle(
    direction_id: str,
    body: DirectionLifecycleMutationInput,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        result = career_profile_service.set_profile_direction_lifecycle(
            db,
            user_pk=_user_pk(db, current_user),
            expected_profile_version=body.expected_profile_version,
            direction_id=direction_id,
            lifecycle=body.lifecycle,
            confirmation=body.confirmation,
        )
        db.commit()
        return result
    except career_profile_service.CareerProfileError as exc:
        db.rollback()
        raise _profile_error(exc) from exc


@router.get("/career-profile/drafts", response_model=list[CareerProfileDraftView])
def list_profile_drafts(
    include_resolved: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return career_profile_service.list_profile_draft_views(
            db,
            user_pk=_user_pk(db, current_user),
            include_resolved=include_resolved,
        )
    except career_profile_service.CareerProfileError as exc:
        raise _profile_error(exc) from exc


@router.post(
    "/career-profile/drafts", response_model=CareerProfileDraftView, status_code=201
)
def create_profile_draft(
    body: CareerProfileDraftInput,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        result = career_profile_service.create_profile_draft_change(
            db, user_pk=_user_pk(db, current_user), draft=body
        )
        db.commit()
        return career_profile_service.profile_draft_view(
            db, user_pk=_user_pk(db, current_user), draft_id=result.id
        )
    except career_profile_service.CareerProfileError as exc:
        db.rollback()
        raise _profile_error(exc) from exc


@router.post(
    "/career-profile/drafts/{draft_id}/accept", response_model=CareerProfileView
)
def accept_profile_draft(
    draft_id: str,
    body: CareerProfileDraftResolutionInput,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if body.expected_profile_version is None:
        raise HTTPException(
            status_code=422, detail="expected_profile_version is required"
        )
    try:
        result = career_profile_service.accept_profile_draft_change(
            db,
            user_pk=_user_pk(db, current_user),
            draft_id=draft_id,
            expected_draft_version=body.expected_draft_version,
            expected_profile_version=body.expected_profile_version,
        )
        db.commit()
        return result
    except career_profile_service.CareerProfileError as exc:
        db.rollback()
        raise _profile_error(exc) from exc


@router.post(
    "/career-profile/drafts/{draft_id}/reject", response_model=CareerProfileDraftView
)
def reject_profile_draft(
    draft_id: str,
    body: CareerProfileDraftResolutionInput,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        result = career_profile_service.reject_profile_draft_change(
            db,
            user_pk=_user_pk(db, current_user),
            draft_id=draft_id,
            expected_draft_version=body.expected_draft_version,
            resolution_note=body.resolution_note,
        )
        db.commit()
        return career_profile_service.profile_draft_view(
            db, user_pk=_user_pk(db, current_user), draft_id=result.id
        )
    except career_profile_service.CareerProfileError as exc:
        db.rollback()
        raise _profile_error(exc) from exc


@router.post(
    "/career-profile/drafts/{draft_id}/candidates/resolve",
    response_model=CareerProfileCandidateResolutionView,
)
def resolve_profile_candidates(
    draft_id: str,
    body: CareerProfileCandidateBatchResolutionInput,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        result = career_profile_service.resolve_profile_candidate_items(
            db,
            user_pk=_user_pk(db, current_user),
            draft_id=draft_id,
            resolution=body,
        )
        db.commit()
        return result
    except career_profile_service.CareerProfileError as exc:
        db.rollback()
        raise _profile_error(exc) from exc


@router.get("/ability-signals", response_model=list[AbilitySignalView])
def read_ability_signals(
    include_inactive: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return ability_signal_service.list_ability_signals(
        db,
        user_pk=_user_pk(db, current_user),
        include_inactive=include_inactive,
    )


@router.get("/ability-signals/{signal_id}", response_model=AbilitySignalView)
def read_ability_signal(
    signal_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return ability_signal_service.get_ability_signal(
            db, user_pk=_user_pk(db, current_user), signal_id=signal_id
        )
    except ability_signal_service.AbilitySignalError as exc:
        raise _ability_error(exc) from exc


@router.post(
    "/interviews/{interview_record_id}/ability-signals/recompute",
    response_model=list[AbilitySignalView],
)
def recompute_interview_ability_signals(
    interview_record_id: str,
    body: AbilitySignalRecomputeInput,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    del body  # reason is user-facing context; source facts drive recomputation.
    try:
        result = ability_signal_service.project_interview_ability_signals(
            db,
            user_pk=_user_pk(db, current_user),
            interview_record_id=interview_record_id,
            force_new_generation=True,
        )
        db.commit()
        return result
    except ability_signal_service.AbilitySignalError as exc:
        db.rollback()
        raise _ability_error(exc) from exc


@router.post("/ability-signals/{signal_id}/dispute", response_model=AbilitySignalView)
def dispute_ability_signal(
    signal_id: str,
    body: AbilitySignalStatusChangeInput,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _change_signal_status(
        "dispute", signal_id, body, current_user=current_user, db=db
    )


@router.post(
    "/ability-signals/{signal_id}/invalidate", response_model=AbilitySignalView
)
def invalidate_ability_signal(
    signal_id: str,
    body: AbilitySignalStatusChangeInput,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _change_signal_status(
        "invalidate", signal_id, body, current_user=current_user, db=db
    )


def _change_signal_status(
    operation: str,
    signal_id: str,
    body: AbilitySignalStatusChangeInput,
    *,
    current_user: User,
    db: Session,
) -> AbilitySignalView:
    try:
        change = (
            ability_signal_service.dispute_ability_signal
            if operation == "dispute"
            else ability_signal_service.invalidate_ability_signal
        )
        result = change(
            db,
            user_pk=_user_pk(db, current_user),
            signal_id=signal_id,
            expected_version=body.expected_version,
            reason=body.reason,
        )
        db.commit()
        return result
    except ability_signal_service.AbilitySignalError as exc:
        db.rollback()
        raise _ability_error(exc) from exc
