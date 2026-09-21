"""Recover UI commands across response loss, process death and browser reload.

The exact command is registered durably before business execution. Execution
and its Operation/verification/receipt link commit atomically. A cancellation
uses the same account lock, including a tombstone for a request not yet received.
Thus a delayed original POST cannot create an invitation after cancellation.
Only an opaque idempotency key needs to survive in browser sessionStorage.
"""

from __future__ import annotations

import hashlib
import json

from sqlalchemy.orm import Session

from app.db.types import utc_now
from app.models.application_operation import ApplicationOperation, OperationVerification
from app.models.invitation_submission import InvitationSubmission
from app.models.user import User
from app.schemas.interview_invitation import (
    ConfirmInterviewInvitation,
    ConfirmInterviewInvitationResult,
)

from .interview_invitation_operations import (
    InvitationIdempotencyConflictError,
    InvitationObjectNotFoundError,
    InvitationPolicyDeniedError,
    InvitationStateConflictError,
    InvitationVerificationError,
    confirm_interview_invitation,
)


def _identity(user_pk: int, key: str) -> str:
    if not 1 <= len(key) <= 200:
        raise InvitationStateConflictError("invalid submission identity")
    return hashlib.sha256(f"{user_pk}:{key}".encode()).hexdigest()


def _lock_owner(db: Session, user_pk: int) -> None:
    # Lock order is account -> submission -> domain. No network/model call is
    # made while holding it. PostgreSQL is the supported concurrent backend.
    owner = db.query(User).filter(User.id == user_pk).with_for_update().one_or_none()
    if owner is None:
        raise InvitationObjectNotFoundError("user")


def _load(db: Session, user_pk: int, key: str) -> InvitationSubmission | None:
    return db.get(InvitationSubmission, _identity(user_pk, key), populate_existing=True)


def register_submission(
    db: Session, *, user_pk: int, command: ConfirmInterviewInvitation
) -> None:
    """Commit ONLY the ingress command. Never mutates an opportunity/interview."""
    if command.actor_kind != "user":
        raise InvitationPolicyDeniedError("UI submission requires a user actor")
    _lock_owner(db, user_pk)
    request = command.model_dump(mode="json")
    digest = hashlib.sha256(
        json.dumps(
            request, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
    ).hexdigest()
    row = _load(db, user_pk, command.idempotency_key)
    if row is not None:
        if row.status == "cancelled":
            raise InvitationStateConflictError("submission_cancelled")
        if row.request_fingerprint != digest:
            raise InvitationIdempotencyConflictError(command.idempotency_key)
        if row.status == "rejected":
            raise InvitationStateConflictError("submission_rejected")
    else:
        pending = (
            db.query(InvitationSubmission)
            .filter_by(user_id=user_pk, status="pending")
            .count()
        )
        if pending >= 20:
            raise InvitationStateConflictError(
                "too_many_unresolved_invitation_submissions"
            )
        db.add(
            InvitationSubmission(
                id=_identity(user_pk, command.idempotency_key),
                user_id=user_pk,
                request_json=request,
                request_fingerprint=digest,
                status="pending",
            )
        )
    db.commit()


def _verified_result(
    db: Session, row: InvitationSubmission
) -> ConfirmInterviewInvitationResult:
    operation = (
        db.get(ApplicationOperation, row.operation_id) if row.operation_id else None
    )
    if (
        operation is None
        or operation.user_id != row.user_id
        or operation.operation_name != "confirm_interview_invitation"
        or operation.status not in {"succeeded", "reconciled"}
    ):
        raise InvitationVerificationError(
            "submission has no committed operation receipt"
        )
    result = ConfirmInterviewInvitationResult.model_validate(operation.result_json)
    verification = db.get(OperationVerification, result.verification.id)
    if (
        result.operation_id != operation.id
        or verification is None
        or verification.operation_id != operation.id
        or verification.conclusion not in {"verified", "reconciled"}
        or result.verification.conclusion != verification.conclusion
    ):
        raise InvitationVerificationError("operation verification receipt mismatch")
    return result.model_copy(update={"replayed": True})


def execute_submission(
    db: Session, *, user_pk: int, key: str
) -> ConfirmInterviewInvitationResult:
    """Caller commits the operation and receipt link together, or rolls back."""
    _lock_owner(db, user_pk)
    row = _load(db, user_pk, key)
    if row is None:
        raise InvitationObjectNotFoundError("invitation submission")
    if row.status == "committed":
        return _verified_result(db, row)
    if row.status != "pending" or not isinstance(row.request_json, dict):
        raise InvitationStateConflictError(f"submission_{row.status}")
    command = ConfirmInterviewInvitation.model_validate(row.request_json)
    if command.idempotency_key != key:
        raise InvitationIdempotencyConflictError("submission key mismatch")
    result = confirm_interview_invitation(db, user_pk=user_pk, command=command)
    row.operation_id = result.operation_id
    row.status = "committed"
    row.updated_at = utc_now()
    db.flush()
    return result


def reject_uncommitted_submission(
    db: Session, *, user_pk: int, key: str, code: str
) -> None:
    """Only for a deterministic pre-commit domain rejection, after rollback.

    Never call this following a lost COMMIT acknowledgement. A successful
    concurrent retry is authoritative and must never be overwritten.
    """
    _lock_owner(db, user_pk)
    row = _load(db, user_pk, key)
    if row is not None and row.status == "pending":
        row.status = "rejected"
        row.rejection_code = code[:80]
        row.updated_at = utc_now()
        db.flush()


def submission_view(db: Session, *, user_pk: int, key: str) -> dict:
    row = _load(db, user_pk, key)
    if row is None:
        # Not found is NOT proof that a delayed original POST cannot arrive.
        return {
            "status": "not_received",
            "idempotency_key": key,
            "result": None,
            "command": None,
        }
    return {
        "status": row.status,
        "idempotency_key": key,
        "result": _verified_result(db, row).model_dump(mode="json")
        if row.status == "committed"
        else None,
        "command": row.request_json if row.status == "pending" else None,
    }


def cancel_submission(db: Session, *, user_pk: int, key: str) -> dict:
    """Cancel ingress, not an already committed interview; keep a tombstone."""
    _lock_owner(db, user_pk)
    row = _load(db, user_pk, key)
    if row is None:
        row = InvitationSubmission(
            id=_identity(user_pk, key), user_id=user_pk, status="cancelled"
        )
        db.add(row)
    elif row.status == "committed":
        return submission_view(db, user_pk=user_pk, key=key)
    else:
        row.status = "cancelled"
        row.request_json = None  # Cancelled drafts need not retain personal data.
        row.updated_at = utc_now()
    db.flush()
    return submission_view(db, user_pk=user_pk, key=key)
