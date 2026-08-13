"""Application-service invariants for saved Artifact versions.

This module only flushes. API, Agent Tool, and prescribed Flow handlers must
commit it in their own transaction after the corresponding explicit user or
Flow command has been accepted. There is intentionally no hook that turns an
ordinary assistant answer into an Artifact.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeAlias

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.types import utc_now
from app.models.artifact import (
    Artifact,
    ArtifactJobRelation,
    ArtifactSubmissionSnapshot,
    ArtifactVersion,
)
from app.models.chat import Conversation, ConversationMessage
from app.models.conversation_turn import ConversationTurn
from app.models.file_asset import FileAsset
from app.schemas.artifact import ArtifactProvenanceInput, ArtifactWriteInput
from app.services.uploads.file_asset_service import (
    READABLE_UPLOAD_STATUSES,
    file_asset_version_token,
)

OwnerChecker: TypeAlias = Callable[[Session, int, str, str], bool]
SubmissionProofChecker: TypeAlias = Callable[[Session, int, str, str, str, str], bool]


class ArtifactDomainError(ValueError):
    pass


class ArtifactConflictError(ArtifactDomainError):
    pass


class ArtifactNotFoundError(ArtifactDomainError):
    pass


class ArtifactOwnershipError(ArtifactDomainError):
    pass


class ArtifactArchivedError(ArtifactDomainError):
    pass


class ArtifactSourceUnavailableError(ArtifactDomainError):
    pass


class ArtifactSubmissionProofError(ArtifactDomainError):
    pass


def save_artifact_explicitly(
    db: Session,
    *,
    user_pk: int,
    operation_key: str,
    artifact_kind: str,
    version: ArtifactWriteInput,
    source_owner_checker: OwnerChecker | None = None,
) -> Artifact:
    """Create an Artifact for an already accepted explicit save command."""

    return _create_artifact(
        db,
        user_pk=user_pk,
        operation_key=operation_key,
        artifact_kind=artifact_kind,
        origin_kind="explicit_save",
        version=version,
        source_owner_checker=source_owner_checker,
    )


def promote_message_to_artifact(
    db: Session,
    *,
    user_pk: int,
    operation_key: str,
    artifact_kind: str,
    title: str,
    source_message_id: int,
    source_turn_id: str | None = None,
) -> Artifact:
    """Explicitly promote one owned user/assistant message into an Artifact."""

    normalized_key = _identity(operation_key, "operation_key")
    normalized_kind = _kind(artifact_kind)
    normalized_title = _title(title)
    normalized_turn_id = _optional_identity(source_turn_id, "source_turn_id")
    existing = _artifact_for_creation_key(db, user_pk, normalized_key)
    if existing is not None:
        initial = _initial_version(db, existing.id)
        if (
            existing.kind == normalized_kind
            and initial.origin_kind == "message_promotion"
            and initial.title == normalized_title
            and initial.source_message_id == source_message_id
            and initial.source_turn_id == normalized_turn_id
        ):
            return existing
        raise ArtifactConflictError(normalized_key)

    message = _require_owned_message(db, user_pk, source_message_id)
    if message.role.lower() not in {"user", "assistant"}:
        raise ArtifactSourceUnavailableError(str(source_message_id))
    if normalized_turn_id is not None:
        turn = _require_owned_turn(db, user_pk, normalized_turn_id)
        if turn.conversation_id != message.conversation_id:
            raise ArtifactSourceUnavailableError(normalized_turn_id)

    version = ArtifactWriteInput(
        title=normalized_title,
        content_text=message.content,
        content_format="plain_text",
        provenance=ArtifactProvenanceInput(
            source_message_id=source_message_id,
            source_turn_id=normalized_turn_id,
        ),
    )
    return _create_artifact(
        db,
        user_pk=user_pk,
        operation_key=normalized_key,
        artifact_kind=normalized_kind,
        origin_kind="message_promotion",
        version=version,
    )


def deliver_flow_artifact(
    db: Session,
    *,
    user_pk: int,
    operation_key: str,
    artifact_kind: str,
    version: ArtifactWriteInput,
    flow_owner_checker: OwnerChecker,
) -> Artifact:
    """Persist the declared output of a prescribed product Flow.

    A Flow delivery must point to its real domain owner and pass that owner's
    ownership checker. Arbitrary model output is not a Flow delivery.
    """

    if (
        version.provenance.source_owner_type is None
        or version.provenance.source_owner_id is None
    ):
        raise ArtifactOwnershipError("flow owner identity is required")
    return _create_artifact(
        db,
        user_pk=user_pk,
        operation_key=operation_key,
        artifact_kind=artifact_kind,
        origin_kind="flow_delivery",
        version=version,
        source_owner_checker=flow_owner_checker,
    )


def edit_artifact(
    db: Session,
    *,
    user_pk: int,
    artifact_id: str,
    operation_key: str,
    version: ArtifactWriteInput,
    source_owner_checker: OwnerChecker | None = None,
) -> ArtifactVersion:
    """Append a new immutable version and thereby make it current."""

    normalized_artifact_id = _identity(artifact_id, "artifact_id")
    normalized_key = _identity(operation_key, "operation_key")
    artifact = _owned_artifact_locked(db, user_pk, normalized_artifact_id)
    existing = (
        db.query(ArtifactVersion)
        .filter(
            ArtifactVersion.artifact_id == artifact.id,
            ArtifactVersion.operation_key == normalized_key,
        )
        .one_or_none()
    )
    payload = _version_payload(version)
    if existing is not None:
        if (
            payload["file_asset_id"] is not None
            and payload["file_asset_version"] is None
        ):
            payload["file_asset_version"] = existing.file_asset_version
        if _version_matches(existing, origin_kind="edit", payload=payload):
            return existing
        raise ArtifactConflictError(normalized_key)
    if artifact.archived_at is not None:
        raise ArtifactArchivedError(artifact.id)
    resolved_file_version = _validate_version_sources(
        db,
        user_pk=user_pk,
        version=version,
        source_owner_checker=source_owner_checker,
    )
    if payload["file_asset_id"] is not None:
        payload["file_asset_version"] = resolved_file_version

    next_no = (
        db.query(func.max(ArtifactVersion.version_no))
        .filter(ArtifactVersion.artifact_id == artifact.id)
        .scalar()
        or 0
    ) + 1
    row = ArtifactVersion(
        artifact_id=artifact.id,
        version_no=next_no,
        operation_key=normalized_key,
        origin_kind="edit",
        **payload,
    )
    artifact.updated_at = utc_now()
    db.add_all([artifact, row])
    db.flush()
    return row


def get_current_artifact_version(
    db: Session,
    *,
    user_pk: int,
    artifact_id: str,
    include_archived: bool = False,
) -> ArtifactVersion:
    artifact = _owned_artifact(db, user_pk, _identity(artifact_id, "artifact_id"))
    if artifact is None or (artifact.archived_at is not None and not include_archived):
        raise ArtifactNotFoundError(artifact_id)
    row = (
        db.query(ArtifactVersion)
        .filter(ArtifactVersion.artifact_id == artifact.id)
        .order_by(ArtifactVersion.version_no.desc())
        .first()
    )
    if row is None:
        raise ArtifactNotFoundError(artifact.id)
    return row


def list_artifacts(
    db: Session,
    *,
    user_pk: int,
    include_archived: bool = False,
    limit: int = 20,
    offset: int = 0,
) -> list[tuple[Artifact, ArtifactVersion]]:
    """Return one bounded user-owned row per Artifact with its current version."""

    if limit < 1 or limit > 100:
        raise ArtifactDomainError("limit")
    if offset < 0:
        raise ArtifactDomainError("offset")

    current_numbers = (
        db.query(
            ArtifactVersion.artifact_id.label("artifact_id"),
            func.max(ArtifactVersion.version_no).label("version_no"),
        )
        .group_by(ArtifactVersion.artifact_id)
        .subquery()
    )
    query = (
        db.query(Artifact, ArtifactVersion)
        .join(current_numbers, current_numbers.c.artifact_id == Artifact.id)
        .join(
            ArtifactVersion,
            (ArtifactVersion.artifact_id == current_numbers.c.artifact_id)
            & (ArtifactVersion.version_no == current_numbers.c.version_no),
        )
        .filter(Artifact.user_id == user_pk)
    )
    if not include_archived:
        query = query.filter(Artifact.archived_at.is_(None))
    return list(
        query.order_by(Artifact.updated_at.desc(), Artifact.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def list_artifact_versions(
    db: Session,
    *,
    user_pk: int,
    artifact_id: str,
) -> list[ArtifactVersion]:
    """Return the immutable version history for one owned Artifact."""

    artifact = _owned_artifact(
        db,
        user_pk,
        _identity(artifact_id, "artifact_id"),
    )
    if artifact is None:
        raise ArtifactNotFoundError(artifact_id)
    return list(
        db.query(ArtifactVersion)
        .filter(ArtifactVersion.artifact_id == artifact.id)
        .order_by(ArtifactVersion.version_no.desc())
        .all()
    )


def list_artifact_job_relations(
    db: Session,
    *,
    user_pk: int,
    artifact_id: str,
) -> list[ArtifactJobRelation]:
    """Return explicit ``related`` links without implying actual use."""

    artifact = _owned_artifact(
        db,
        user_pk,
        _identity(artifact_id, "artifact_id"),
    )
    if artifact is None:
        raise ArtifactNotFoundError(artifact_id)
    return list(
        db.query(ArtifactJobRelation)
        .filter(
            ArtifactJobRelation.artifact_id == artifact.id,
            ArtifactJobRelation.user_id == user_pk,
        )
        .order_by(
            ArtifactJobRelation.created_at.desc(),
            ArtifactJobRelation.id.desc(),
        )
        .all()
    )


def list_artifact_submissions(
    db: Session,
    *,
    user_pk: int,
    artifact_id: str,
) -> list[tuple[ArtifactSubmissionSnapshot, ArtifactVersion]]:
    """Return actual-use snapshots joined to their frozen exact versions."""

    artifact = _owned_artifact(
        db,
        user_pk,
        _identity(artifact_id, "artifact_id"),
    )
    if artifact is None:
        raise ArtifactNotFoundError(artifact_id)
    return list(
        db.query(ArtifactSubmissionSnapshot, ArtifactVersion)
        .join(
            ArtifactVersion,
            ArtifactVersion.id == ArtifactSubmissionSnapshot.artifact_version_id,
        )
        .filter(
            ArtifactSubmissionSnapshot.artifact_id == artifact.id,
            ArtifactSubmissionSnapshot.user_id == user_pk,
        )
        .order_by(
            ArtifactSubmissionSnapshot.submitted_at.desc(),
            ArtifactSubmissionSnapshot.id.desc(),
        )
        .all()
    )


def archive_artifact(
    db: Session,
    *,
    user_pk: int,
    artifact_id: str,
) -> Artifact:
    """Idempotently archive an Artifact without deleting versions or blobs."""

    artifact = _owned_artifact_locked(
        db,
        user_pk,
        _identity(artifact_id, "artifact_id"),
    )
    if artifact.archived_at is None:
        now = utc_now()
        artifact.archived_at = now
        artifact.updated_at = now
        db.add(artifact)
        db.flush()
    return artifact


def relate_artifact_to_job(
    db: Session,
    *,
    user_pk: int,
    artifact_id: str,
    job_opportunity_id: str,
    job_owner_checker: OwnerChecker,
) -> ArtifactJobRelation:
    """Create the weak ``related`` relation; it never means submitted."""

    artifact = _require_active_artifact(db, user_pk, artifact_id)
    normalized_job_id = _identity(job_opportunity_id, "job_opportunity_id")
    _require_external_owner(
        db,
        user_pk,
        "job_opportunity",
        normalized_job_id,
        job_owner_checker,
    )
    return _ensure_related(db, user_pk, artifact.id, normalized_job_id)


def record_user_confirmed_submission(
    db: Session,
    *,
    user_pk: int,
    operation_key: str,
    artifact_id: str,
    artifact_version_id: str,
    job_opportunity_id: str,
    confirmation_message_id: int,
    job_owner_checker: OwnerChecker,
) -> ArtifactSubmissionSnapshot:
    """Freeze exact-version use based on an owned explicit user assertion."""

    return _record_submission(
        db,
        user_pk=user_pk,
        operation_key=operation_key,
        artifact_id=artifact_id,
        artifact_version_id=artifact_version_id,
        job_opportunity_id=job_opportunity_id,
        basis="user_confirmation",
        confirmation_message_id=confirmation_message_id,
        receipt_owner_type=None,
        receipt_owner_id=None,
        job_owner_checker=job_owner_checker,
        proof_checker=None,
    )


def record_receipt_confirmed_submission(
    db: Session,
    *,
    user_pk: int,
    operation_key: str,
    artifact_id: str,
    artifact_version_id: str,
    job_opportunity_id: str,
    receipt_owner_type: str,
    receipt_owner_id: str,
    job_owner_checker: OwnerChecker,
    proof_checker: SubmissionProofChecker,
) -> ArtifactSubmissionSnapshot:
    """Freeze exact-version use only after a real receipt/read-back checker."""

    return _record_submission(
        db,
        user_pk=user_pk,
        operation_key=operation_key,
        artifact_id=artifact_id,
        artifact_version_id=artifact_version_id,
        job_opportunity_id=job_opportunity_id,
        basis="external_receipt",
        confirmation_message_id=None,
        receipt_owner_type=_identity(receipt_owner_type, "receipt_owner_type", 64),
        receipt_owner_id=_identity(receipt_owner_id, "receipt_owner_id"),
        job_owner_checker=job_owner_checker,
        proof_checker=proof_checker,
    )


def record_product_ui_confirmed_submission(
    db: Session,
    *,
    user_pk: int,
    operation_key: str,
    artifact_id: str,
    artifact_version_id: str,
    job_opportunity_id: str,
    job_owner_checker: OwnerChecker,
) -> ArtifactSubmissionSnapshot:
    """Freeze exact-version use from an authenticated explicit UI command.

    The stable operation key is the auditable product-command identity. No
    ConversationMessage is fabricated merely to satisfy this boundary.
    """

    return _record_submission(
        db,
        user_pk=user_pk,
        operation_key=operation_key,
        artifact_id=artifact_id,
        artifact_version_id=artifact_version_id,
        job_opportunity_id=job_opportunity_id,
        basis="product_ui_confirmation",
        confirmation_message_id=None,
        receipt_owner_type=None,
        receipt_owner_id=None,
        job_owner_checker=job_owner_checker,
        proof_checker=None,
    )


def _create_artifact(
    db: Session,
    *,
    user_pk: int,
    operation_key: str,
    artifact_kind: str,
    origin_kind: str,
    version: ArtifactWriteInput,
    source_owner_checker: OwnerChecker | None = None,
) -> Artifact:
    normalized_key = _identity(operation_key, "operation_key")
    normalized_kind = _kind(artifact_kind)
    payload = _version_payload(version)
    existing = _artifact_for_creation_key(db, user_pk, normalized_key)
    if existing is not None:
        initial = _initial_version(db, existing.id)
        if (
            payload["file_asset_id"] is not None
            and payload["file_asset_version"] is None
        ):
            payload["file_asset_version"] = initial.file_asset_version
        if existing.kind == normalized_kind and _version_matches(
            initial,
            origin_kind=origin_kind,
            payload=payload,
        ):
            return existing
        raise ArtifactConflictError(normalized_key)
    resolved_file_version = _validate_version_sources(
        db,
        user_pk=user_pk,
        version=version,
        source_owner_checker=source_owner_checker,
    )
    if payload["file_asset_id"] is not None:
        payload["file_asset_version"] = resolved_file_version

    artifact = Artifact(
        user_id=user_pk,
        kind=normalized_kind,
        creation_key=normalized_key,
    )
    db.add(artifact)
    db.flush()
    initial = ArtifactVersion(
        artifact_id=artifact.id,
        version_no=1,
        operation_key=normalized_key,
        origin_kind=origin_kind,
        **payload,
    )
    db.add(initial)
    db.flush()
    return artifact


def _record_submission(
    db: Session,
    *,
    user_pk: int,
    operation_key: str,
    artifact_id: str,
    artifact_version_id: str,
    job_opportunity_id: str,
    basis: str,
    confirmation_message_id: int | None,
    receipt_owner_type: str | None,
    receipt_owner_id: str | None,
    job_owner_checker: OwnerChecker,
    proof_checker: SubmissionProofChecker | None,
) -> ArtifactSubmissionSnapshot:
    normalized_key = _identity(operation_key, "operation_key")
    normalized_artifact_id = _identity(artifact_id, "artifact_id")
    normalized_version_id = _identity(artifact_version_id, "artifact_version_id")
    normalized_job_id = _identity(job_opportunity_id, "job_opportunity_id")
    existing = (
        db.query(ArtifactSubmissionSnapshot)
        .filter(
            ArtifactSubmissionSnapshot.user_id == user_pk,
            ArtifactSubmissionSnapshot.operation_key == normalized_key,
        )
        .one_or_none()
    )
    expected = (
        normalized_job_id,
        normalized_artifact_id,
        normalized_version_id,
        basis,
        confirmation_message_id,
        receipt_owner_type,
        receipt_owner_id,
    )
    if existing is not None:
        actual = (
            existing.job_opportunity_id,
            existing.artifact_id,
            existing.artifact_version_id,
            existing.basis,
            existing.confirmation_message_id,
            existing.receipt_owner_type,
            existing.receipt_owner_id,
        )
        if actual == expected:
            return existing
        raise ArtifactConflictError(normalized_key)

    artifact = _require_active_artifact(db, user_pk, normalized_artifact_id)
    version = (
        db.query(ArtifactVersion)
        .filter(
            ArtifactVersion.id == normalized_version_id,
            ArtifactVersion.artifact_id == artifact.id,
        )
        .one_or_none()
    )
    if version is None:
        raise ArtifactNotFoundError(normalized_version_id)
    _require_external_owner(
        db,
        user_pk,
        "job_opportunity",
        normalized_job_id,
        job_owner_checker,
    )

    if basis == "user_confirmation":
        if confirmation_message_id is None:
            raise ArtifactSubmissionProofError("confirmation message is required")
        message = _require_owned_message(db, user_pk, confirmation_message_id)
        if message.role.lower() != "user":
            raise ArtifactSubmissionProofError(str(confirmation_message_id))
    elif basis == "product_ui_confirmation":
        if any(
            value is not None
            for value in (
                confirmation_message_id,
                receipt_owner_type,
                receipt_owner_id,
            )
        ):
            raise ArtifactSubmissionProofError("invalid product UI confirmation shape")
    elif basis == "external_receipt":
        if (
            receipt_owner_type is None
            or receipt_owner_id is None
            or proof_checker is None
            or not proof_checker(
                db,
                user_pk,
                normalized_job_id,
                version.id,
                receipt_owner_type,
                receipt_owner_id,
            )
        ):
            raise ArtifactSubmissionProofError(receipt_owner_id or "receipt")
    else:
        raise ArtifactSubmissionProofError(basis)

    _ensure_related(db, user_pk, artifact.id, normalized_job_id)
    row = ArtifactSubmissionSnapshot(
        user_id=user_pk,
        operation_key=normalized_key,
        job_opportunity_id=normalized_job_id,
        artifact_id=artifact.id,
        artifact_version_id=version.id,
        basis=basis,
        confirmation_message_id=confirmation_message_id,
        receipt_owner_type=receipt_owner_type,
        receipt_owner_id=receipt_owner_id,
    )
    db.add(row)
    db.flush()
    return row


def _validate_version_sources(
    db: Session,
    *,
    user_pk: int,
    version: ArtifactWriteInput,
    source_owner_checker: OwnerChecker | None,
) -> str | None:
    payload = _version_payload(version)
    message = None
    turn = None
    source_message_id = payload["source_message_id"]
    source_turn_id = payload["source_turn_id"]
    source_owner_type = payload["source_owner_type"]
    source_owner_id = payload["source_owner_id"]
    if source_message_id is not None:
        message = _require_owned_message(db, user_pk, int(source_message_id))
    if source_turn_id is not None:
        turn = _require_owned_turn(db, user_pk, str(source_turn_id))
    if message is not None and turn is not None:
        if message.conversation_id != turn.conversation_id:
            raise ArtifactSourceUnavailableError(str(source_turn_id))
    if source_owner_type is not None:
        if source_owner_checker is None:
            raise ArtifactOwnershipError(str(source_owner_id or "source"))
        _require_external_owner(
            db,
            user_pk,
            str(source_owner_type),
            str(source_owner_id or ""),
            source_owner_checker,
        )

    file_asset_id = payload["file_asset_id"]
    file_asset_version = payload["file_asset_version"]
    if file_asset_id is not None:
        asset = (
            db.query(FileAsset)
            .filter(
                FileAsset.id == file_asset_id,
                FileAsset.user_id == user_pk,
                FileAsset.deleted_at.is_(None),
            )
            .one_or_none()
        )
        if (
            asset is None
            or asset.upload_status not in READABLE_UPLOAD_STATUSES
            or asset.validation_status != "passed"
        ):
            raise ArtifactSourceUnavailableError(file_asset_id)
        if (
            file_asset_version is not None
            and file_asset_version != file_asset_version_token(asset)
        ):
            raise ArtifactSourceUnavailableError(str(file_asset_version))
        return file_asset_version_token(asset)
    return None


def _version_payload(version: ArtifactWriteInput) -> dict[str, object]:
    provenance = version.provenance
    return {
        "title": _title(version.title),
        "content_text": version.content_text,
        "content_format": _identity(version.content_format, "content_format", 64),
        "file_asset_id": _optional_identity(version.file_asset_id, "file_asset_id"),
        "file_asset_version": _optional_identity(
            version.file_asset_version,
            "file_asset_version",
            96,
        ),
        "source_message_id": provenance.source_message_id,
        "source_turn_id": _optional_identity(
            provenance.source_turn_id,
            "source_turn_id",
        ),
        "source_owner_type": _optional_identity(
            provenance.source_owner_type,
            "source_owner_type",
            64,
        ),
        "source_owner_id": _optional_identity(
            provenance.source_owner_id,
            "source_owner_id",
        ),
    }


def _version_matches(
    row: ArtifactVersion,
    *,
    origin_kind: str,
    payload: dict[str, object],
) -> bool:
    return row.origin_kind == origin_kind and all(
        getattr(row, key) == value for key, value in payload.items()
    )


def _owned_artifact(db: Session, user_pk: int, artifact_id: str) -> Artifact | None:
    return (
        db.query(Artifact)
        .filter(Artifact.id == artifact_id, Artifact.user_id == user_pk)
        .one_or_none()
    )


def _owned_artifact_locked(db: Session, user_pk: int, artifact_id: str) -> Artifact:
    artifact = (
        db.query(Artifact)
        .filter(Artifact.id == artifact_id, Artifact.user_id == user_pk)
        .with_for_update()
        .one_or_none()
    )
    if artifact is None:
        raise ArtifactNotFoundError(artifact_id)
    return artifact


def _require_active_artifact(db: Session, user_pk: int, artifact_id: str) -> Artifact:
    artifact = _owned_artifact_locked(
        db,
        user_pk,
        _identity(artifact_id, "artifact_id"),
    )
    if artifact.archived_at is not None:
        raise ArtifactArchivedError(artifact.id)
    return artifact


def _artifact_for_creation_key(
    db: Session,
    user_pk: int,
    operation_key: str,
) -> Artifact | None:
    return (
        db.query(Artifact)
        .filter(
            Artifact.user_id == user_pk,
            Artifact.creation_key == operation_key,
        )
        .one_or_none()
    )


def _initial_version(db: Session, artifact_id: str) -> ArtifactVersion:
    row = (
        db.query(ArtifactVersion)
        .filter(
            ArtifactVersion.artifact_id == artifact_id,
            ArtifactVersion.version_no == 1,
        )
        .one_or_none()
    )
    if row is None:
        raise ArtifactNotFoundError(artifact_id)
    return row


def _require_owned_message(
    db: Session,
    user_pk: int,
    message_id: int,
) -> ConversationMessage:
    row = (
        db.query(ConversationMessage)
        .join(Conversation, Conversation.id == ConversationMessage.conversation_id)
        .filter(
            ConversationMessage.id == message_id,
            Conversation.user_id == user_pk,
        )
        .one_or_none()
    )
    if row is None:
        raise ArtifactSourceUnavailableError(str(message_id))
    return row


def _require_owned_turn(db: Session, user_pk: int, turn_id: str) -> ConversationTurn:
    row = (
        db.query(ConversationTurn)
        .filter(
            ConversationTurn.id == turn_id,
            ConversationTurn.user_id == user_pk,
        )
        .one_or_none()
    )
    if row is None:
        raise ArtifactSourceUnavailableError(turn_id)
    return row


def _require_external_owner(
    db: Session,
    user_pk: int,
    owner_type: str,
    owner_id: str,
    checker: OwnerChecker,
) -> None:
    if not checker(db, user_pk, owner_type, owner_id):
        raise ArtifactOwnershipError(owner_id)


def _ensure_related(
    db: Session,
    user_pk: int,
    artifact_id: str,
    job_opportunity_id: str,
) -> ArtifactJobRelation:
    existing = (
        db.query(ArtifactJobRelation)
        .filter(
            ArtifactJobRelation.artifact_id == artifact_id,
            ArtifactJobRelation.job_opportunity_id == job_opportunity_id,
        )
        .one_or_none()
    )
    if existing is not None:
        if existing.user_id != user_pk:
            raise ArtifactOwnershipError(job_opportunity_id)
        return existing
    row = ArtifactJobRelation(
        user_id=user_pk,
        artifact_id=artifact_id,
        job_opportunity_id=job_opportunity_id,
    )
    db.add(row)
    db.flush()
    return row


def _identity(value: str, field: str, max_length: int = 128) -> str:
    normalized = (value or "").strip()
    if not normalized or len(normalized) > max_length:
        raise ArtifactDomainError(field)
    return normalized


def _optional_identity(
    value: str | None,
    field: str,
    max_length: int = 128,
) -> str | None:
    return None if value is None else _identity(value, field, max_length)


def _kind(value: str) -> str:
    return _identity(value, "artifact_kind", 64)


def _title(value: str) -> str:
    return _identity(value, "title", 240)


__all__ = [
    "ArtifactArchivedError",
    "ArtifactConflictError",
    "ArtifactDomainError",
    "ArtifactNotFoundError",
    "ArtifactOwnershipError",
    "ArtifactSourceUnavailableError",
    "ArtifactSubmissionProofError",
    "archive_artifact",
    "deliver_flow_artifact",
    "edit_artifact",
    "get_current_artifact_version",
    "list_artifact_job_relations",
    "list_artifact_submissions",
    "list_artifact_versions",
    "list_artifacts",
    "promote_message_to_artifact",
    "record_receipt_confirmed_submission",
    "record_product_ui_confirmed_submission",
    "record_user_confirmed_submission",
    "relate_artifact_to_job",
    "save_artifact_explicitly",
]
