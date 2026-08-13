"""Draft-to-claim lifecycle for Conversation attachment ingress.

The durable product identities stay FileAsset + AttachmentRef.  The existing
KnowledgeDocument row is reused only as the asynchronous parsing projection;
it has no Conversation scope until admission claims the draft.  This module
flushes but never commits or dispatches workers.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.db.types import utc_now
from app.models.chat import Conversation
from app.models.conversation_attachment import (
    ConversationAttachmentDraft,
    ConversationAttachmentRef,
)
from app.models.conversation_turn import ConversationTurn
from app.models.file_asset import FileAsset
from app.models.knowledge import KnowledgeDocument
from app.services.knowledge.document_formats import (
    UnsupportedDocumentFormat,
    validate_knowledge_document_format,
)
from app.services.uploads.file_asset_service import mark_file_asset_consumed


class AttachmentIngressError(ValueError):
    """Base error for rejected attachment-ingress commands."""


class AttachmentDraftConflictError(AttachmentIngressError):
    """A stable draft identity was reused for different input."""


class AttachmentDraftUnavailableError(AttachmentIngressError):
    """The draft is absent, removed, already claimed, or outside the owner scope."""


class AttachmentAssetUnavailableError(AttachmentIngressError):
    """The source FileAsset is absent, deleted, failed, or not byte-ready."""


class AttachmentClaimConflictError(AttachmentIngressError):
    """A submission identity was retried with a different claim payload."""


def create_attachment_draft(
    db: Session,
    *,
    user_pk: int,
    conversation_id: str,
    file_asset_id: str,
    draft_id: str | None = None,
) -> ConversationAttachmentDraft:
    """Persist a Composer selection without granting Conversation/RAG scope.

    Supplying ``draft_id`` makes client retries idempotent.  The caller has
    already confirmed the raw bytes; parsing may continue asynchronously.
    """

    normalized_conversation_id = _identity(conversation_id, "conversation_id")
    normalized_file_asset_id = _identity(file_asset_id, "file_asset_id")
    normalized_draft_id = _optional_identity(draft_id, "draft_id")

    _require_owned_conversation(db, user_pk, normalized_conversation_id)
    asset = _owned_asset(db, user_pk, normalized_file_asset_id)
    if asset is None or asset.upload_status in {"failed", "delete_pending", "deleted"}:
        raise AttachmentAssetUnavailableError(normalized_file_asset_id)

    if normalized_draft_id is not None:
        existing = db.get(ConversationAttachmentDraft, normalized_draft_id)
        if existing is not None:
            if (
                existing.user_id == user_pk
                and existing.conversation_id == normalized_conversation_id
                and existing.file_asset_id == normalized_file_asset_id
                and existing.removed_at is None
            ):
                return existing
            raise AttachmentDraftConflictError(normalized_draft_id)

    if not _asset_is_claimable(asset) or asset.upload_status != "uploaded":
        raise AttachmentAssetUnavailableError(normalized_file_asset_id)
    try:
        validate_knowledge_document_format(asset.original_filename, asset.content_type)
    except UnsupportedDocumentFormat as exc:
        raise AttachmentAssetUnavailableError(str(exc)) from exc

    projection = KnowledgeDocument(
        user_id=user_pk,
        conversation_id=None,
        file_asset_id=asset.id,
        title=asset.original_filename,
        category="会话附件",
        source_kind="chat_attachment",
        storage_uri=asset.storage_uri,
        object_key=asset.object_key,
        status="processing",
    )
    db.add(projection)
    db.flush()
    mark_file_asset_consumed(db, asset)

    draft = ConversationAttachmentDraft(
        **({"id": normalized_draft_id} if normalized_draft_id is not None else {}),
        user_id=user_pk,
        conversation_id=normalized_conversation_id,
        file_asset_id=normalized_file_asset_id,
        source_document_id=projection.id,
    )
    db.add(draft)
    db.flush()
    return draft


def remove_attachment_draft(
    db: Session,
    *,
    user_pk: int,
    conversation_id: str,
    draft_id: str,
) -> ConversationAttachmentDraft:
    """Idempotently revoke an unclaimed draft without touching its FileAsset."""

    normalized_conversation_id = _identity(conversation_id, "conversation_id")
    normalized_draft_id = _identity(draft_id, "draft_id")
    draft = (
        db.query(ConversationAttachmentDraft)
        .filter(
            ConversationAttachmentDraft.id == normalized_draft_id,
            ConversationAttachmentDraft.user_id == user_pk,
            ConversationAttachmentDraft.conversation_id == normalized_conversation_id,
        )
        .with_for_update()
        .one_or_none()
    )
    if draft is None:
        raise AttachmentDraftUnavailableError(normalized_draft_id)

    claimed = (
        db.query(ConversationAttachmentRef.id)
        .filter(ConversationAttachmentRef.draft_id == normalized_draft_id)
        .first()
    )
    if claimed is not None:
        raise AttachmentDraftUnavailableError(normalized_draft_id)

    if draft.removed_at is None:
        now = utc_now()
        draft.removed_at = now
        draft.updated_at = now
        db.add(draft)
        db.flush()
    return draft


def claim_attachment_drafts(
    db: Session,
    *,
    user_pk: int,
    conversation_id: str,
    turn_id: str,
    submission_id: str,
    draft_ids: Sequence[str],
) -> list[ConversationAttachmentRef]:
    """Freeze ordered AttachmentRefs exactly once for an admitted Turn.

    A retry with the same Conversation/submission/Turn and ordered draft set
    returns the existing rows.  Reusing either the submission identity with a
    different payload or a claimed draft for another submission is rejected.
    The caller must commit this flush in the same transaction that accepts the
    Turn; on any exception it must roll the entire admission back.
    """

    normalized_conversation_id = _identity(conversation_id, "conversation_id")
    normalized_turn_id = _identity(turn_id, "turn_id")
    normalized_submission_id = _identity(submission_id, "submission_id")
    normalized_draft_ids = [_identity(value, "draft_id") for value in draft_ids]
    if len(normalized_draft_ids) != len(set(normalized_draft_ids)):
        raise AttachmentClaimConflictError("duplicate draft_id")

    _require_owned_conversation(db, user_pk, normalized_conversation_id)
    turn = (
        db.query(ConversationTurn)
        .filter(
            ConversationTurn.id == normalized_turn_id,
            ConversationTurn.user_id == user_pk,
            ConversationTurn.conversation_id == normalized_conversation_id,
        )
        .one_or_none()
    )
    if turn is None:
        raise AttachmentClaimConflictError(normalized_turn_id)
    if (
        turn.submission_id is not None
        and turn.submission_id != normalized_submission_id
    ):
        raise AttachmentClaimConflictError(normalized_submission_id)

    # A frozen claim outlives its transient draft rows.  Read it before draft
    # validation so a later transport retry remains idempotent even after
    # claimed-draft cleanup.
    existing = _submission_refs(
        db,
        normalized_conversation_id,
        normalized_submission_id,
    )
    if existing:
        return _match_existing_claim(
            existing,
            user_pk=user_pk,
            turn_id=normalized_turn_id,
            submission_id=normalized_submission_id,
            draft_ids=normalized_draft_ids,
        )

    if not normalized_draft_ids:
        return []

    # Lock drafts before checking existing claims.  On databases that support
    # row locks this serializes concurrent claims; unique constraints remain
    # the final guard and a transaction retry resolves to the idempotent read.
    drafts = (
        db.query(ConversationAttachmentDraft)
        .filter(
            ConversationAttachmentDraft.id.in_(normalized_draft_ids),
            ConversationAttachmentDraft.user_id == user_pk,
            ConversationAttachmentDraft.conversation_id == normalized_conversation_id,
        )
        .with_for_update()
        .all()
    )
    drafts_by_id = {draft.id: draft for draft in drafts}
    missing = [
        draft_id for draft_id in normalized_draft_ids if draft_id not in drafts_by_id
    ]
    if missing:
        raise AttachmentDraftUnavailableError(missing[0])

    # Re-read after taking the draft locks.  A concurrent identical claim may
    # have committed while this transaction waited for those locks.
    existing = _submission_refs(
        db,
        normalized_conversation_id,
        normalized_submission_id,
    )
    if existing:
        return _match_existing_claim(
            existing,
            user_pk=user_pk,
            turn_id=normalized_turn_id,
            submission_id=normalized_submission_id,
            draft_ids=normalized_draft_ids,
        )

    for draft_id in normalized_draft_ids:
        if drafts_by_id[draft_id].removed_at is not None:
            raise AttachmentDraftUnavailableError(draft_id)

    prior_claim = (
        db.query(ConversationAttachmentRef.draft_id)
        .filter(ConversationAttachmentRef.draft_id.in_(normalized_draft_ids))
        .first()
    )
    if prior_claim is not None:
        raise AttachmentDraftUnavailableError(prior_claim[0])

    asset_ids = [
        drafts_by_id[draft_id].file_asset_id for draft_id in normalized_draft_ids
    ]
    assets = (
        db.query(FileAsset)
        .filter(
            FileAsset.id.in_(asset_ids),
            FileAsset.user_id == user_pk,
            FileAsset.deleted_at.is_(None),
        )
        .with_for_update()
        .all()
    )
    assets_by_id = {asset.id: asset for asset in assets}
    projection_ids = [
        drafts_by_id[draft_id].source_document_id for draft_id in normalized_draft_ids
    ]
    projections = (
        db.query(KnowledgeDocument)
        .filter(
            KnowledgeDocument.id.in_(projection_ids),
            KnowledgeDocument.user_id == user_pk,
            KnowledgeDocument.deleted_at.is_(None),
        )
        .with_for_update()
        .all()
    )
    projections_by_id = {projection.id: projection for projection in projections}
    refs: list[ConversationAttachmentRef] = []
    for position, draft_id in enumerate(normalized_draft_ids):
        draft = drafts_by_id[draft_id]
        asset = assets_by_id.get(draft.file_asset_id)
        if not _asset_is_claimable(asset):
            raise AttachmentAssetUnavailableError(draft.file_asset_id)
        projection = projections_by_id.get(draft.source_document_id)
        if (
            projection is None
            or projection.source_kind != "chat_attachment"
            or projection.file_asset_id != draft.file_asset_id
            or projection.file_asset_id != asset.id
        ):
            raise AttachmentAssetUnavailableError(draft.file_asset_id)
        if projection.conversation_id not in {None, normalized_conversation_id}:
            raise AttachmentClaimConflictError(draft.id)
        projection.conversation_id = normalized_conversation_id
        ref = ConversationAttachmentRef(
            draft_id=draft.id,
            user_id=user_pk,
            conversation_id=normalized_conversation_id,
            turn_id=normalized_turn_id,
            submission_id=normalized_submission_id,
            position=position,
            file_asset_id=asset.id,
            source_document_id=projection.id,
            file_asset_version=_file_asset_version(asset),
            display_name=asset.original_filename,
        )
        refs.append(ref)

    db.add_all(refs)
    db.flush()
    return refs


def preflight_attachment_drafts(
    db: Session,
    *,
    user_pk: int,
    conversation_id: str,
    submission_id: str,
    draft_ids: Sequence[str],
) -> None:
    """Lock and validate a future claim without creating or changing rows.

    Admission calls this before it creates the UserMessage/Turn.  Keeping the
    same transaction open preserves the locks through the later real claim,
    so an invalid queued source can fail the ``PendingSubmission`` without a
    savepoint that first creates and then rolls back Interaction Records.

    Parsing may be processing, ready, or failed: the raw-byte gate is what
    permits admission, while parse state is surfaced separately and a failed
    projection can be retried under the same identity.
    """

    normalized_conversation_id = _identity(conversation_id, "conversation_id")
    normalized_submission_id = _identity(submission_id, "submission_id")
    normalized_draft_ids = [_identity(value, "draft_id") for value in draft_ids]
    if len(normalized_draft_ids) != len(set(normalized_draft_ids)):
        raise AttachmentClaimConflictError("duplicate draft_id")

    _require_owned_conversation(db, user_pk, normalized_conversation_id)
    if _submission_refs(db, normalized_conversation_id, normalized_submission_id):
        raise AttachmentClaimConflictError(normalized_submission_id)
    if not normalized_draft_ids:
        return

    drafts = (
        db.query(ConversationAttachmentDraft)
        .filter(
            ConversationAttachmentDraft.id.in_(normalized_draft_ids),
            ConversationAttachmentDraft.user_id == user_pk,
            ConversationAttachmentDraft.conversation_id == normalized_conversation_id,
        )
        .with_for_update()
        .all()
    )
    drafts_by_id = {draft.id: draft for draft in drafts}
    missing = [
        draft_id for draft_id in normalized_draft_ids if draft_id not in drafts_by_id
    ]
    if missing:
        raise AttachmentDraftUnavailableError(missing[0])
    removed = next(
        (
            draft_id
            for draft_id in normalized_draft_ids
            if drafts_by_id[draft_id].removed_at is not None
        ),
        None,
    )
    if removed is not None:
        raise AttachmentDraftUnavailableError(removed)

    prior_claim = (
        db.query(ConversationAttachmentRef.draft_id)
        .filter(ConversationAttachmentRef.draft_id.in_(normalized_draft_ids))
        .first()
    )
    if prior_claim is not None:
        raise AttachmentDraftUnavailableError(prior_claim[0])

    asset_ids = [
        drafts_by_id[draft_id].file_asset_id for draft_id in normalized_draft_ids
    ]
    assets = (
        db.query(FileAsset)
        .filter(
            FileAsset.id.in_(asset_ids),
            FileAsset.user_id == user_pk,
            FileAsset.deleted_at.is_(None),
        )
        .with_for_update()
        .all()
    )
    assets_by_id = {asset.id: asset for asset in assets}
    projection_ids = [
        drafts_by_id[draft_id].source_document_id for draft_id in normalized_draft_ids
    ]
    projections = (
        db.query(KnowledgeDocument)
        .filter(
            KnowledgeDocument.id.in_(projection_ids),
            KnowledgeDocument.user_id == user_pk,
            KnowledgeDocument.deleted_at.is_(None),
        )
        .with_for_update()
        .all()
    )
    projections_by_id = {projection.id: projection for projection in projections}

    for draft_id in normalized_draft_ids:
        draft = drafts_by_id[draft_id]
        asset = assets_by_id.get(draft.file_asset_id)
        if not _asset_is_claimable(asset):
            raise AttachmentAssetUnavailableError(draft.file_asset_id)
        projection = projections_by_id.get(draft.source_document_id)
        if (
            projection is None
            or projection.source_kind != "chat_attachment"
            or projection.file_asset_id != draft.file_asset_id
            or projection.file_asset_id != asset.id
        ):
            raise AttachmentAssetUnavailableError(draft.file_asset_id)
        if projection.conversation_id not in {None, normalized_conversation_id}:
            raise AttachmentClaimConflictError(draft.id)
        # Computing the version here is the immutable-blob consistency gate;
        # the real claim freezes this exact value after the Turn exists.
        if not _file_asset_version(asset):  # pragma: no cover - defensive
            raise AttachmentAssetUnavailableError(draft.file_asset_id)


def attachment_ref_snapshot(ref: ConversationAttachmentRef) -> dict[str, object]:
    """Return the structured identity future History/SourceResolver adapters use."""

    return {
        "attachment_ref_id": ref.id,
        "file_asset_id": ref.file_asset_id,
        "document_id": ref.source_document_id,
        "file_asset_version": ref.file_asset_version,
        "title": ref.display_name,
        "position": ref.position,
        "scope": {
            "kind": "conversation",
            "conversation_id": ref.conversation_id,
        },
    }


def get_attachment_draft(
    db: Session,
    *,
    user_pk: int,
    conversation_id: str,
    draft_id: str,
) -> tuple[ConversationAttachmentDraft, KnowledgeDocument]:
    """Return one owned draft and its asynchronous parsing projection."""

    draft = (
        db.query(ConversationAttachmentDraft)
        .filter(
            ConversationAttachmentDraft.id == _identity(draft_id, "draft_id"),
            ConversationAttachmentDraft.user_id == user_pk,
            ConversationAttachmentDraft.conversation_id
            == _identity(conversation_id, "conversation_id"),
        )
        .one_or_none()
    )
    if draft is None:
        raise AttachmentDraftUnavailableError(draft_id)
    projection = db.get(KnowledgeDocument, draft.source_document_id)
    if projection is None or projection.user_id != user_pk:
        raise AttachmentAssetUnavailableError(draft.file_asset_id)
    return draft, projection


def _submission_refs(
    db: Session,
    conversation_id: str,
    submission_id: str,
) -> list[ConversationAttachmentRef]:
    return (
        db.query(ConversationAttachmentRef)
        .filter(
            ConversationAttachmentRef.conversation_id == conversation_id,
            ConversationAttachmentRef.submission_id == submission_id,
        )
        .order_by(ConversationAttachmentRef.position.asc())
        .all()
    )


def _match_existing_claim(
    refs: list[ConversationAttachmentRef],
    *,
    user_pk: int,
    turn_id: str,
    submission_id: str,
    draft_ids: Sequence[str],
) -> list[ConversationAttachmentRef]:
    if all(ref.user_id == user_pk and ref.turn_id == turn_id for ref in refs) and [
        ref.draft_id for ref in refs
    ] == list(draft_ids):
        return refs
    raise AttachmentClaimConflictError(submission_id)


def _require_owned_conversation(
    db: Session,
    user_pk: int,
    conversation_id: str,
) -> Conversation:
    conversation = (
        db.query(Conversation)
        .filter(
            Conversation.id == conversation_id,
            Conversation.user_id == user_pk,
            Conversation.archived_at.is_(None),
        )
        .one_or_none()
    )
    if conversation is None:
        raise AttachmentDraftUnavailableError(conversation_id)
    return conversation


def _owned_asset(db: Session, user_pk: int, file_asset_id: str) -> FileAsset | None:
    return (
        db.query(FileAsset)
        .filter(
            FileAsset.id == file_asset_id,
            FileAsset.user_id == user_pk,
            FileAsset.deleted_at.is_(None),
        )
        .one_or_none()
    )


def _asset_is_claimable(asset: FileAsset | None) -> bool:
    return bool(
        asset is not None
        and asset.upload_status in {"uploaded", "consumed"}
        and asset.validation_status == "passed"
        and asset.deleted_at is None
    )


def _file_asset_version(asset: FileAsset) -> str:
    checksum = (asset.checksum_sha256 or "").strip().lower()
    # A FileAsset id identifies one immutable uploaded blob.  Prefer the
    # content hash where available; otherwise the asset identity itself is the
    # version token.  Replacement creates a new FileAsset instead of rewriting
    # an existing AttachmentRef.
    return f"sha256:{checksum}" if checksum else f"file_asset:{asset.id}"


def _identity(value: str, field: str) -> str:
    normalized = (value or "").strip()
    if not normalized or len(normalized) > 128:
        raise AttachmentIngressError(field)
    return normalized


def _optional_identity(value: str | None, field: str) -> str | None:
    return None if value is None else _identity(value, field)


__all__ = [
    "AttachmentAssetUnavailableError",
    "AttachmentClaimConflictError",
    "AttachmentDraftConflictError",
    "AttachmentDraftUnavailableError",
    "AttachmentIngressError",
    "attachment_ref_snapshot",
    "claim_attachment_drafts",
    "create_attachment_draft",
    "get_attachment_draft",
    "preflight_attachment_drafts",
    "remove_attachment_draft",
]
