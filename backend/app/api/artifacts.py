"""Explicit Artifact commands and exact-version application-use routes.

There is no endpoint that automatically converts an assistant response into
an Artifact. Every write below is a named user action and delegates to the
same Artifact Application Service used by future typed Agent handlers.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.models.artifact import Artifact, ArtifactVersion
from app.models.interview_record import InterviewRecord
from app.models.job_opportunity import JobOpportunity
from app.models.user import User
from app.schemas.artifact import (
    ArtifactEditRequest,
    ArtifactExplicitSaveRequest,
    ArtifactMessagePromotionRequest,
    ArtifactRelatedRequest,
    ArtifactRelatedView,
    ArtifactSubmittedRequest,
    ArtifactSubmissionDetailView,
    ArtifactSubmissionView,
    ArtifactView,
    ArtifactVersionView,
)
from app.services import artifact_service

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


def _direct_source_owner_checker(
    db: Session,
    user_pk: int,
    owner_type: str,
    owner_id: str,
) -> bool:
    """Check only concrete owners implemented by the current product.

    This explicit dispatch is deliberately not a polymorphic Source Registry.
    """

    if owner_type == "job_opportunity":
        return (
            db.query(JobOpportunity.id)
            .filter(
                JobOpportunity.id == owner_id,
                JobOpportunity.user_id == user_pk,
            )
            .scalar()
            is not None
        )
    if owner_type == "interview_record":
        return (
            db.query(InterviewRecord.id)
            .filter(
                InterviewRecord.id == owner_id,
                InterviewRecord.user_id == user_pk,
            )
            .scalar()
            is not None
        )
    return False


def _job_owner_checker(
    db: Session,
    user_pk: int,
    owner_type: str,
    owner_id: str,
) -> bool:
    return owner_type == "job_opportunity" and _direct_source_owner_checker(
        db,
        user_pk,
        owner_type,
        owner_id,
    )


def _artifact_view(
    db: Session,
    artifact: Artifact,
    *,
    include_archived: bool = False,
) -> ArtifactView:
    current = artifact_service.get_current_artifact_version(
        db,
        user_pk=artifact.user_id,
        artifact_id=artifact.id,
        include_archived=include_archived,
    )
    return _artifact_view_with_version(artifact, current)


def _artifact_view_with_version(
    artifact: Artifact,
    current_version: ArtifactVersion,
) -> ArtifactView:
    return ArtifactView(
        id=artifact.id,
        kind=artifact.kind,
        archived_at=artifact.archived_at,
        current_version=ArtifactVersionView.model_validate(current_version),
    )


def _owned_artifact(db: Session, user_pk: int, artifact_id: str) -> Artifact:
    row = (
        db.query(Artifact)
        .filter(Artifact.id == artifact_id, Artifact.user_id == user_pk)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return row


def _raise_artifact_http(exc: artifact_service.ArtifactDomainError) -> None:
    if isinstance(
        exc,
        (
            artifact_service.ArtifactNotFoundError,
            artifact_service.ArtifactOwnershipError,
            artifact_service.ArtifactSourceUnavailableError,
        ),
    ):
        raise HTTPException(
            status_code=404, detail="Artifact or source not found"
        ) from exc
    if isinstance(
        exc,
        (
            artifact_service.ArtifactConflictError,
            artifact_service.ArtifactArchivedError,
        ),
    ):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, artifact_service.ArtifactSubmissionProofError):
        raise HTTPException(
            status_code=422, detail="Submission proof is invalid"
        ) from exc
    raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("", response_model=ArtifactView, status_code=201)
def save_artifact(
    body: ArtifactExplicitSaveRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        artifact = artifact_service.save_artifact_explicitly(
            db,
            user_pk=current_user.id,
            operation_key=body.operation_key,
            artifact_kind=body.artifact_kind,
            version=body.version,
            source_owner_checker=_direct_source_owner_checker,
        )
        db.commit()
        return _artifact_view(db, artifact)
    except artifact_service.ArtifactDomainError as exc:
        db.rollback()
        _raise_artifact_http(exc)


@router.post("/from-message", response_model=ArtifactView, status_code=201)
def promote_message(
    body: ArtifactMessagePromotionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        artifact = artifact_service.promote_message_to_artifact(
            db,
            user_pk=current_user.id,
            operation_key=body.operation_key,
            artifact_kind=body.artifact_kind,
            title=body.title,
            source_message_id=body.source_message_id,
            source_turn_id=body.source_turn_id,
        )
        db.commit()
        return _artifact_view(db, artifact)
    except artifact_service.ArtifactDomainError as exc:
        db.rollback()
        _raise_artifact_http(exc)


@router.get("", response_model=list[ArtifactView])
def list_artifacts(
    include_archived: bool = False,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        rows = artifact_service.list_artifacts(
            db,
            user_pk=current_user.id,
            include_archived=include_archived,
            limit=limit,
            offset=offset,
        )
        return [
            _artifact_view_with_version(artifact, current_version)
            for artifact, current_version in rows
        ]
    except artifact_service.ArtifactDomainError as exc:
        _raise_artifact_http(exc)


@router.get("/{artifact_id}", response_model=ArtifactView)
def read_artifact(
    artifact_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    artifact = _owned_artifact(db, current_user.id, artifact_id)
    try:
        # Archive changes default listing/editability, not the existence of an
        # immutable user asset or its history. A direct owner-scoped read must
        # therefore remain available after archive.
        return _artifact_view(db, artifact, include_archived=True)
    except artifact_service.ArtifactDomainError as exc:
        _raise_artifact_http(exc)


@router.get("/{artifact_id}/versions", response_model=list[ArtifactVersionView])
def list_artifact_versions(
    artifact_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return [
            ArtifactVersionView.model_validate(row)
            for row in artifact_service.list_artifact_versions(
                db,
                user_pk=current_user.id,
                artifact_id=artifact_id,
            )
        ]
    except artifact_service.ArtifactDomainError as exc:
        _raise_artifact_http(exc)


@router.get("/{artifact_id}/related", response_model=list[ArtifactRelatedView])
def list_artifact_relations(
    artifact_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return [
            ArtifactRelatedView.model_validate(row)
            for row in artifact_service.list_artifact_job_relations(
                db,
                user_pk=current_user.id,
                artifact_id=artifact_id,
            )
        ]
    except artifact_service.ArtifactDomainError as exc:
        _raise_artifact_http(exc)


@router.get(
    "/{artifact_id}/submissions",
    response_model=list[ArtifactSubmissionDetailView],
)
def list_artifact_submissions(
    artifact_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return [
            ArtifactSubmissionDetailView(
                **ArtifactSubmissionView.model_validate(snapshot).model_dump(),
                submitted_version=ArtifactVersionView.model_validate(version),
            )
            for snapshot, version in artifact_service.list_artifact_submissions(
                db,
                user_pk=current_user.id,
                artifact_id=artifact_id,
            )
        ]
    except artifact_service.ArtifactDomainError as exc:
        _raise_artifact_http(exc)


@router.post("/{artifact_id}/versions", response_model=ArtifactView)
def edit_artifact(
    artifact_id: str,
    body: ArtifactEditRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        artifact_service.edit_artifact(
            db,
            user_pk=current_user.id,
            artifact_id=artifact_id,
            operation_key=body.operation_key,
            version=body.version,
            source_owner_checker=_direct_source_owner_checker,
        )
        db.commit()
        return _artifact_view(db, _owned_artifact(db, current_user.id, artifact_id))
    except artifact_service.ArtifactDomainError as exc:
        db.rollback()
        _raise_artifact_http(exc)


@router.post("/{artifact_id}/archive", response_model=ArtifactView)
def archive_artifact(
    artifact_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        artifact = artifact_service.archive_artifact(
            db,
            user_pk=current_user.id,
            artifact_id=artifact_id,
        )
        db.commit()
        return _artifact_view(db, artifact, include_archived=True)
    except artifact_service.ArtifactDomainError as exc:
        db.rollback()
        _raise_artifact_http(exc)


@router.post("/{artifact_id}/related", response_model=ArtifactRelatedView)
def relate_artifact(
    artifact_id: str,
    body: ArtifactRelatedRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        relation = artifact_service.relate_artifact_to_job(
            db,
            user_pk=current_user.id,
            artifact_id=artifact_id,
            job_opportunity_id=body.job_opportunity_id,
            job_owner_checker=_job_owner_checker,
        )
        db.commit()
        return ArtifactRelatedView.model_validate(relation)
    except artifact_service.ArtifactDomainError as exc:
        db.rollback()
        _raise_artifact_http(exc)


@router.post("/{artifact_id}/submitted", response_model=ArtifactSubmissionView)
def record_submitted_artifact(
    artifact_id: str,
    body: ArtifactSubmittedRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        snapshot = artifact_service.record_user_confirmed_submission(
            db,
            user_pk=current_user.id,
            operation_key=body.operation_key,
            artifact_id=artifact_id,
            artifact_version_id=body.artifact_version_id,
            job_opportunity_id=body.job_opportunity_id,
            confirmation_message_id=body.confirmation_message_id,
            job_owner_checker=_job_owner_checker,
        )
        db.commit()
        return ArtifactSubmissionView.model_validate(snapshot)
    except artifact_service.ArtifactDomainError as exc:
        db.rollback()
        _raise_artifact_http(exc)


__all__ = ["router"]
