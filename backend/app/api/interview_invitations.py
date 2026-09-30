"""Thin authenticated adapters for the VS-01 Shared Operations."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, Query, status
from app.schemas.invitation_submission import SubmissionKey, InvitationSubmissionReceipt
from app.career.application import invitation_submission_service as submissions
from sqlalchemy.orm import Session

from app.career.application.interview_invitation_operations import (
    InvitationIdempotencyConflictError,
    InvitationObjectNotFoundError,
    InvitationOwnershipError,
    InvitationPolicyDeniedError,
    InvitationStateConflictError,
    InvitationVerificationError,
    InvitationVersionConflictError,
    InterviewInvitationOperationError,
    get_interview_invitation_candidate,
    get_interview_invitation_handoff,
    list_interview_invitation_handoffs,
)
from app.career.application.fixture_invitation_adapter import (
    ingest_fixture_interview_invitation,
)
from app.core.security import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.schemas.interview_invitation import (
    ConfirmInterviewInvitation,
    ConfirmInterviewInvitationResult,
    FixtureInterviewInvitationInput,
    FixtureInterviewInvitationResult,
    InterviewInvitationCandidateView,
    InterviewInvitationHandoffView,
)


router = APIRouter(
    prefix="/career/interview-invitations",
    tags=["interview-invitations"],
)


def _http_error(exc: InterviewInvitationOperationError) -> HTTPException:
    if isinstance(exc, (InvitationObjectNotFoundError, InvitationOwnershipError)):
        return HTTPException(
            status_code=404,
            detail={"code": exc.code, "message": "Invitation object not found"},
        )
    if isinstance(
        exc,
        (
            InvitationIdempotencyConflictError,
            InvitationStateConflictError,
            InvitationVersionConflictError,
        ),
    ):
        return HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": str(exc)},
        )
    if isinstance(exc, InvitationPolicyDeniedError):
        return HTTPException(
            status_code=403,
            detail={"code": exc.code, "message": "Operation policy denied"},
        )
    if isinstance(exc, InvitationVerificationError):
        return HTTPException(
            status_code=500,
            detail={"code": exc.code, "message": "Operation verification failed"},
        )
    return HTTPException(
        status_code=422,
        detail={"code": exc.code, "message": str(exc)},
    )


@router.post(
    "/confirm",
    response_model=ConfirmInterviewInvitationResult,
    status_code=status.HTTP_201_CREATED,
)
def confirm_invitation_from_ui(
    payload: ConfirmInterviewInvitation,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConfirmInterviewInvitationResult:
    """Direct UI path; Agent and Automation use their own thin adapters."""

    if payload.actor_kind != "user":
        raise HTTPException(
            status_code=422,
            detail={
                "code": "actor_mismatch",
                "message": "This endpoint only accepts direct user Operations",
            },
        )
    try:
        submissions.register_submission(db, user_pk=current_user.id, command=payload)
        result = submissions.execute_submission(
            db, user_pk=current_user.id, key=payload.idempotency_key
        )
        db.commit()
    except InterviewInvitationOperationError as exc:
        db.rollback()
        # A rejected conflicting replay must not invalidate the original request.
        if not isinstance(exc, InvitationIdempotencyConflictError):
            submissions.reject_uncommitted_submission(
                db,
                user_pk=current_user.id,
                key=payload.idempotency_key,
                code=exc.code,
            )
            db.commit()
        raise _http_error(exc) from exc
    except Exception:
        db.rollback()
        raise
    response.status_code = (
        status.HTTP_200_OK if result.replayed else status.HTTP_201_CREATED
    )
    return result


@router.post(
    "/fixture-observations",
    response_model=FixtureInterviewInvitationResult,
    status_code=status.HTTP_201_CREATED,
)
def ingest_fixture_observation(
    payload: FixtureInterviewInvitationInput,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FixtureInterviewInvitationResult:
    """VS-01 deterministic fixture ingress; this is not a live provider API."""

    try:
        result = ingest_fixture_interview_invitation(
            db,
            user_pk=current_user.id,
            command=payload,
        )
        db.commit()
    except InterviewInvitationOperationError as exc:
        db.rollback()
        raise _http_error(exc) from exc
    except Exception:
        db.rollback()
        raise
    response.status_code = (
        status.HTTP_200_OK if result.replayed else status.HTTP_201_CREATED
    )
    return result


@router.get(
    "/candidates/{candidate_id}",
    response_model=InterviewInvitationCandidateView,
)
def read_invitation_candidate(
    candidate_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> InterviewInvitationCandidateView:
    try:
        return get_interview_invitation_candidate(
            db,
            user_pk=current_user.id,
            candidate_id=candidate_id,
        )
    except InterviewInvitationOperationError as exc:
        raise _http_error(exc) from exc


@router.get(
    "/interviews",
    response_model=list[InterviewInvitationHandoffView],
)
def list_confirmed_invitation_interviews(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[InterviewInvitationHandoffView]:
    return list_interview_invitation_handoffs(
        db,
        user_pk=current_user.id,
    )


@router.get(
    "/interviews/{interview_id}/handoff",
    response_model=InterviewInvitationHandoffView,
)
def read_invitation_handoff(
    interview_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> InterviewInvitationHandoffView:
    try:
        return get_interview_invitation_handoff(
            db,
            user_pk=current_user.id,
            interview_id=interview_id,
        )
    except InterviewInvitationOperationError as exc:
        raise _http_error(exc) from exc


__all__ = ["router"]


@router.get("/submissions/receipt", response_model=InvitationSubmissionReceipt)
def read_submission_receipt(
    idempotency_key: str = Query(min_length=1, max_length=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return submissions.submission_view(
            db, user_pk=current_user.id, key=idempotency_key
        )
    except InterviewInvitationOperationError as exc:
        raise _http_error(exc) from exc


@router.post("/submissions/resume", response_model=ConfirmInterviewInvitationResult)
def resume_submission(
    payload: SubmissionKey,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        result = submissions.execute_submission(
            db, user_pk=current_user.id, key=payload.idempotency_key
        )
        db.commit()
        return result
    except InterviewInvitationOperationError as exc:
        db.rollback()
        raise _http_error(exc) from exc
    except Exception:
        db.rollback()
        raise


@router.post("/submissions/cancel", response_model=InvitationSubmissionReceipt)
def cancel_pending_submission(
    payload: SubmissionKey,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        result = submissions.cancel_submission(
            db, user_pk=current_user.id, key=payload.idempotency_key
        )
        db.commit()
        return result
    except InterviewInvitationOperationError as exc:
        db.rollback()
        raise _http_error(exc) from exc
    except Exception:
        db.rollback()
        raise
