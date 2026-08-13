"""Typed attachment-source state, retry, promotion, and scope cleanup.

``FileAsset`` remains the raw-file owner and ``KnowledgeDocument`` remains the
rebuildable parsing projection.  This service only manages two real grants:
an admitted Conversation ``AttachmentRef`` and an explicit
``InterviewSourceRef`` owned by one existing ``InterviewRecord``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.types import utc_now
from app.models.chat import Conversation
from app.models.conversation_attachment import (
    ConversationAttachmentDraft,
    ConversationAttachmentRef,
)
from app.models.conversation_turn import ConversationTurn
from app.models.document_chunk import DocumentChunk
from app.models.file_asset import FileAsset
from app.models.interview_record import InterviewRecord
from app.models.interview_source import InterviewSourceRef
from app.models.knowledge import KnowledgeDocument
from app.models.pending_submission import PendingSubmission
from app.services.uploads.file_asset_service import file_asset_version_token

AttachmentProcessingStatus = Literal["processing", "ready", "failed"]
AttachmentSourceKind = Literal[
    "draft",
    "conversation_attachment",
    "debrief_project_source",
]
AttachmentScopeKind = Literal[
    "composer_draft",
    "pending_submission",
    "conversation",
    "debrief_project",
]


class AttachmentSourceCommandError(ValueError):
    """A source command failed ownership, scope, version, or state checks."""


class AttachmentSourceNotFoundError(AttachmentSourceCommandError):
    """The caller cannot see the requested source identity."""


class AttachmentSourceConflictError(AttachmentSourceCommandError):
    """The requested state transition is no longer valid."""


@dataclass(frozen=True)
class AttachmentSourceState:
    source_id: str
    source_kind: AttachmentSourceKind
    scope_kind: AttachmentScopeKind
    scope_id: str
    status: AttachmentProcessingStatus
    file_asset_id: str | None
    file_asset_version: str | None
    document_id: str | None
    title: str
    error_message: str | None
    can_retry: bool
    parse_quality: dict[str, object]
    coverage: dict[str, object]


@dataclass(frozen=True)
class AttachmentProjectionRetry:
    state: AttachmentSourceState
    should_dispatch: bool


@dataclass(frozen=True)
class ConversationAttachmentCleanup:
    pending_submissions: int
    drafts: int
    attachment_refs: int
    deleted_projections: int
    preserved_promoted_projections: int
    deleted_file_assets: int
    ingestion_task_ids: tuple[str, ...]


@dataclass(frozen=True)
class InterviewSourceCleanup:
    source_refs: int
    deleted_projections: int
    deleted_file_assets: int
    ingestion_task_ids: tuple[str, ...]


def list_pending_submission_sources(
    db: Session,
    *,
    user_pk: int,
    conversation_id: str,
    submission_id: str,
) -> list[AttachmentSourceState]:
    """Return every queued explicit source in client order, including failures."""

    submission = (
        db.query(PendingSubmission)
        .filter(
            PendingSubmission.id == _identity(submission_id, "submission_id"),
            PendingSubmission.user_id == user_pk,
            PendingSubmission.conversation_id
            == _identity(conversation_id, "conversation_id"),
            PendingSubmission.status.in_(("pending", "failed")),
        )
        .one_or_none()
    )
    if submission is None:
        raise AttachmentSourceNotFoundError(submission_id)

    draft_ids = _draft_ids(submission.attachments_json or [])
    if not draft_ids:
        return []
    rows = (
        db.query(ConversationAttachmentDraft, KnowledgeDocument, FileAsset)
        .outerjoin(
            KnowledgeDocument,
            KnowledgeDocument.id == ConversationAttachmentDraft.source_document_id,
        )
        .outerjoin(
            FileAsset,
            FileAsset.id == ConversationAttachmentDraft.file_asset_id,
        )
        .filter(ConversationAttachmentDraft.id.in_(draft_ids))
        .all()
    )
    by_id = {draft.id: (draft, document, asset) for draft, document, asset in rows}
    states: list[AttachmentSourceState] = []
    for draft_id in draft_ids:
        row = by_id.get(draft_id)
        if row is None:
            states.append(
                _missing_state(
                    source_id=draft_id,
                    source_kind="draft",
                    scope_kind="pending_submission",
                    scope_id=submission.id,
                    reason="附件草稿已不存在，请移除或重新选择文件。",
                )
            )
            continue
        draft, document, asset = row
        states.append(
            _state_for_draft(
                db,
                draft,
                document,
                asset,
                scope_kind="pending_submission",
                scope_id=submission.id,
            )
        )
    return states


def list_claimed_attachment_sources(
    db: Session,
    *,
    user_pk: int,
    conversation_id: str,
    turn_id: str | None = None,
) -> list[AttachmentSourceState]:
    """Return immutable Conversation AttachmentRefs with typed parse state."""

    normalized_conversation_id = _identity(conversation_id, "conversation_id")
    _owned_conversation(db, user_pk, normalized_conversation_id)
    query = (
        db.query(ConversationAttachmentRef, KnowledgeDocument, FileAsset)
        .outerjoin(
            KnowledgeDocument,
            KnowledgeDocument.id == ConversationAttachmentRef.source_document_id,
        )
        .outerjoin(FileAsset, FileAsset.id == ConversationAttachmentRef.file_asset_id)
        .filter(
            ConversationAttachmentRef.user_id == user_pk,
            ConversationAttachmentRef.conversation_id == normalized_conversation_id,
            ConversationAttachmentRef.removed_at.is_(None),
        )
    )
    if turn_id is not None:
        query = query.filter(
            ConversationAttachmentRef.turn_id == _identity(turn_id, "turn_id")
        )
    rows = query.order_by(
        ConversationAttachmentRef.created_at,
        ConversationAttachmentRef.position,
    ).all()
    return [
        _state_for_claimed(db, ref, document, asset) for ref, document, asset in rows
    ]


def list_debrief_project_sources(
    db: Session,
    *,
    user_pk: int,
    interview_record_id: str,
) -> list[AttachmentSourceState]:
    """List only explicitly promoted file sources for one InterviewRecord."""

    normalized_record_id = _identity(interview_record_id, "interview_record_id")
    _owned_interview_record(db, user_pk, normalized_record_id)
    rows = (
        db.query(InterviewSourceRef, KnowledgeDocument, FileAsset)
        .outerjoin(
            KnowledgeDocument,
            KnowledgeDocument.id == InterviewSourceRef.source_document_id,
        )
        .outerjoin(FileAsset, FileAsset.id == InterviewSourceRef.file_asset_id)
        .filter(
            InterviewSourceRef.user_id == user_pk,
            InterviewSourceRef.interview_record_id == normalized_record_id,
            InterviewSourceRef.removed_at.is_(None),
        )
        .order_by(InterviewSourceRef.created_at, InterviewSourceRef.id)
        .all()
    )
    return [
        _state_for_promoted(db, ref, document, asset) for ref, document, asset in rows
    ]


def prepare_attachment_projection_retry(
    db: Session,
    *,
    user_pk: int,
    conversation_id: str,
    source_id: str,
) -> AttachmentProjectionRetry:
    """Move one failed projection back to processing without changing identity.

    The caller commits this transition before dispatching the existing
    ``document_id``.  Concurrent retries observe ``processing`` and do not
    dispatch a duplicate job.
    """

    normalized_conversation_id = _identity(conversation_id, "conversation_id")
    normalized_source_id = _identity(source_id, "source_id")
    conversation = _owned_conversation(db, user_pk, normalized_conversation_id)
    source = _resolve_source_in_conversation(
        db,
        user_pk=user_pk,
        conversation=conversation,
        source_id=normalized_source_id,
        for_update=True,
    )
    document = source[1]
    if document is None or document.deleted_at is not None:
        raise AttachmentSourceConflictError("附件解析投影已删除。")
    asset = source[2]
    if not _asset_is_readable(asset):
        raise AttachmentSourceConflictError("附件原始文件当前不可用。")

    state = _state_from_resolved(db, source)
    if state.status in {"processing", "ready"}:
        return AttachmentProjectionRetry(state=state, should_dispatch=False)

    document.status = "processing"
    document.error_message = None
    document.task_id = None
    document.updated_at = utc_now()
    db.add(document)
    db.flush()
    return AttachmentProjectionRetry(
        state=_state_from_resolved(db, (source[0], document, asset, source[3])),
        should_dispatch=True,
    )


def get_attachment_source_state(
    db: Session,
    *,
    user_pk: int,
    conversation_id: str,
    source_id: str,
) -> AttachmentSourceState:
    """Read one draft, Conversation, or bound Debrief source by typed identity."""

    conversation = _owned_conversation(
        db,
        user_pk,
        _identity(conversation_id, "conversation_id"),
    )
    source = _resolve_source_in_conversation(
        db,
        user_pk=user_pk,
        conversation=conversation,
        source_id=_identity(source_id, "source_id"),
        for_update=False,
    )
    return _state_from_resolved(db, source)


def mark_attachment_retry_dispatch_failed(
    db: Session,
    *,
    document_id: str,
    message: str,
) -> None:
    """Restore an explicit failed state when enqueueing the retry itself fails."""

    document = (
        db.query(KnowledgeDocument)
        .filter(KnowledgeDocument.id == _identity(document_id, "document_id"))
        .with_for_update()
        .one_or_none()
    )
    if document is None or document.status != "processing":
        return
    document.status = "failed"
    document.error_message = (message or "后台处理队列暂时不可用，请稍后重试。")[:500]
    document.updated_at = utc_now()
    db.add(document)
    db.flush()


def promote_attachment_to_debrief(
    db: Session,
    *,
    user_pk: int,
    conversation_id: str,
    attachment_ref_id: str,
) -> InterviewSourceRef:
    """Explicitly grant a Debrief Conversation attachment to its InterviewRecord.

    Promotion reuses the exact FileAsset/version and parsing projection.  It
    never creates an Artifact, CareerProfile candidate, or generic Project.
    """

    normalized_conversation_id = _identity(conversation_id, "conversation_id")
    normalized_ref_id = _identity(attachment_ref_id, "attachment_ref_id")
    conversation = (
        db.query(Conversation)
        .filter(
            Conversation.id == normalized_conversation_id,
            Conversation.user_id == user_pk,
            Conversation.archived_at.is_(None),
        )
        .with_for_update()
        .one_or_none()
    )
    if (
        conversation is None
        or conversation.type != "debrief"
        or conversation.subject_type != "interview_record"
        or not conversation.subject_id
    ):
        raise AttachmentSourceConflictError(
            "只有已绑定 InterviewRecord 的复盘对话可以晋升本次复盘资料。"
        )
    record = _owned_interview_record(db, user_pk, conversation.subject_id)
    ref, document, asset = db.query(
        ConversationAttachmentRef, KnowledgeDocument, FileAsset
    ).join(
        KnowledgeDocument,
        KnowledgeDocument.id == ConversationAttachmentRef.source_document_id,
    ).join(FileAsset, FileAsset.id == ConversationAttachmentRef.file_asset_id).filter(
        ConversationAttachmentRef.id == normalized_ref_id,
        ConversationAttachmentRef.user_id == user_pk,
        ConversationAttachmentRef.conversation_id == normalized_conversation_id,
        ConversationAttachmentRef.removed_at.is_(None),
    ).with_for_update().one_or_none() or (None, None, None)
    if ref is None or document is None or asset is None:
        raise AttachmentSourceNotFoundError(normalized_ref_id)
    if not _claimed_owner_is_valid(ref, document, asset):
        raise AttachmentSourceConflictError("附件来源身份、版本或原始文件已失效。")

    existing = (
        db.query(InterviewSourceRef)
        .filter(
            InterviewSourceRef.interview_record_id == record.id,
            InterviewSourceRef.file_asset_id == ref.file_asset_id,
            InterviewSourceRef.file_asset_version == ref.file_asset_version,
        )
        .with_for_update()
        .one_or_none()
    )
    if existing is not None:
        if existing.user_id != user_pk:
            raise AttachmentSourceConflictError("复盘来源所有权不一致。")
        existing.removed_at = None
        db.add(existing)
        if existing.source_document_id == document.id:
            # A promoted projection must not retain a cascading Conversation owner.
            document.conversation_id = None
            db.add(document)
        db.flush()
        return existing

    promoted = InterviewSourceRef(
        interview_record_id=record.id,
        user_id=user_pk,
        file_asset_id=ref.file_asset_id,
        source_document_id=ref.source_document_id,
        file_asset_version=ref.file_asset_version,
        display_name=ref.display_name,
        origin_conversation_id=ref.conversation_id,
        origin_attachment_ref_id=ref.id,
    )
    # ``knowledge_documents.conversation_id`` has ON DELETE CASCADE.  Once the
    # explicit InterviewRecord grant exists, clear that legacy physical owner;
    # both Conversation and Debrief scope are henceforth enforced by refs.
    document.conversation_id = None
    db.add_all([promoted, document])
    db.flush()
    return promoted


def remove_debrief_project_source(
    db: Session,
    *,
    user_pk: int,
    interview_record_id: str,
    source_ref_id: str,
) -> InterviewSourceRef:
    """Remove only the InterviewRecord scope grant; preserve other scopes."""

    normalized_record_id = _identity(interview_record_id, "interview_record_id")
    _owned_interview_record(db, user_pk, normalized_record_id)
    ref = (
        db.query(InterviewSourceRef)
        .filter(
            InterviewSourceRef.id == _identity(source_ref_id, "source_ref_id"),
            InterviewSourceRef.interview_record_id == normalized_record_id,
            InterviewSourceRef.user_id == user_pk,
        )
        .with_for_update()
        .one_or_none()
    )
    if ref is None:
        raise AttachmentSourceNotFoundError(source_ref_id)
    if ref.removed_at is not None:
        return ref

    ref.removed_at = utc_now()
    document = db.get(KnowledgeDocument, ref.source_document_id)
    origin_ref = (
        db.query(ConversationAttachmentRef)
        .filter(
            ConversationAttachmentRef.id == ref.origin_attachment_ref_id,
            ConversationAttachmentRef.user_id == user_pk,
        )
        .one_or_none()
    )
    if document is not None and origin_ref is not None:
        origin_conversation = db.get(Conversation, origin_ref.conversation_id)
        if origin_conversation is not None:
            document.conversation_id = origin_ref.conversation_id
            db.add(document)
    db.add(ref)
    db.flush()
    return ref


def remove_conversation_attachment_from_scope(
    db: Session,
    *,
    user_pk: int,
    conversation_id: str,
    attachment_ref_id: str,
) -> tuple[ConversationAttachmentRef, str]:
    """Revoke one admitted source from future Conversation reads.

    The immutable claim identity and frozen asset version stay available to
    History.  Only the Conversation read grant is revoked.  When the owning
    Turn is waiting on attachment parsing, the API rechecks whether the same
    Turn can now resume; no new user message or Turn is created.
    """

    normalized_conversation_id = _identity(conversation_id, "conversation_id")
    normalized_ref_id = _identity(attachment_ref_id, "attachment_ref_id")
    _owned_conversation(db, user_pk, normalized_conversation_id)
    ref = (
        db.query(ConversationAttachmentRef)
        .filter(
            ConversationAttachmentRef.id == normalized_ref_id,
            ConversationAttachmentRef.user_id == user_pk,
            ConversationAttachmentRef.conversation_id == normalized_conversation_id,
        )
        .with_for_update()
        .one_or_none()
    )
    if ref is None:
        raise AttachmentSourceNotFoundError(normalized_ref_id)
    turn = (
        db.query(ConversationTurn)
        .filter(
            ConversationTurn.id == ref.turn_id,
            ConversationTurn.user_id == user_pk,
            ConversationTurn.conversation_id == normalized_conversation_id,
        )
        .with_for_update()
        .one_or_none()
    )
    if turn is None:
        raise AttachmentSourceNotFoundError(ref.turn_id)
    if ref.removed_at is not None:
        return ref, turn.id
    ref.removed_at = utc_now()
    db.add(ref)
    db.flush()
    return ref, turn.id


def cleanup_conversation_attachment_scope(
    db: Session,
    *,
    user_pk: int,
    conversation_id: str,
) -> ConversationAttachmentCleanup:
    """Withdraw queued input and release every Conversation-local file grant.

    The caller first blocks new admission and safely terminalizes the active
    Turn, then invokes this function inside the same transaction that deletes
    the Conversation.  Promoted InterviewRecord sources and formal Artifact /
    Resume / Interview references remain intact.
    """

    normalized_conversation_id = _identity(conversation_id, "conversation_id")
    _owned_conversation(db, user_pk, normalized_conversation_id, include_archived=True)

    pending = (
        db.query(PendingSubmission)
        .filter(
            PendingSubmission.conversation_id == normalized_conversation_id,
            PendingSubmission.user_id == user_pk,
        )
        .with_for_update()
        .all()
    )
    drafts = (
        db.query(ConversationAttachmentDraft)
        .filter(
            ConversationAttachmentDraft.conversation_id == normalized_conversation_id,
            ConversationAttachmentDraft.user_id == user_pk,
        )
        .with_for_update()
        .all()
    )
    claimed_refs = (
        db.query(ConversationAttachmentRef)
        .filter(
            ConversationAttachmentRef.conversation_id == normalized_conversation_id,
            ConversationAttachmentRef.user_id == user_pk,
        )
        .with_for_update()
        .all()
    )
    document_ids = {
        *(draft.source_document_id for draft in drafts),
        *(ref.source_document_id for ref in claimed_refs),
    }
    documents = (
        db.query(KnowledgeDocument)
        .filter(
            KnowledgeDocument.id.in_(document_ids),
            KnowledgeDocument.user_id == user_pk,
        )
        .with_for_update()
        .all()
        if document_ids
        else []
    )
    promoted_document_ids = {
        document_id
        for (document_id,) in db.query(InterviewSourceRef.source_document_id)
        .filter(
            InterviewSourceRef.user_id == user_pk,
            InterviewSourceRef.source_document_id.in_(document_ids),
        )
        .all()
    }

    for row in pending:
        db.delete(row)
    for row in claimed_refs:
        db.delete(row)
    for row in drafts:
        db.delete(row)
    db.flush()

    deleted_projections = 0
    preserved_promoted = 0
    deleted_file_assets = 0
    ingestion_task_ids: list[str] = []
    for document in documents:
        if document.task_id:
            ingestion_task_ids.append(document.task_id)
        if document.id in promoted_document_ids:
            document.conversation_id = None
            db.add(document)
            preserved_promoted += 1
            continue
        if _projection_has_other_scope(db, document.id):
            continue

        asset = (
            db.get(FileAsset, document.file_asset_id)
            if document.file_asset_id
            else None
        )
        from app.services.knowledge.knowledge_service import (
            delete_document_vectors_and_chunks,
        )

        delete_document_vectors_and_chunks(db, document)
        db.delete(document)
        db.flush()
        deleted_projections += 1
        if asset is not None and not _asset_has_durable_reference(db, asset.id):
            from app.services.uploads.file_asset_service import (
                enqueue_asset_blob_delete,
            )

            enqueue_asset_blob_delete(db, asset)
            db.delete(asset)
            db.flush()
            deleted_file_assets += 1

    return ConversationAttachmentCleanup(
        pending_submissions=len(pending),
        drafts=len(drafts),
        attachment_refs=len(claimed_refs),
        deleted_projections=deleted_projections,
        preserved_promoted_projections=preserved_promoted,
        deleted_file_assets=deleted_file_assets,
        ingestion_task_ids=tuple(dict.fromkeys(ingestion_task_ids)),
    )


def cleanup_interview_source_scope(
    db: Session,
    *,
    user_pk: int,
    interview_record_id: str,
) -> InterviewSourceCleanup:
    """Release explicitly promoted files when their InterviewRecord is deleted.

    Linked Debrief Conversations must be cleaned first.  Formal Artifact,
    Resume, or other Interview references still protect a shared FileAsset.
    """

    normalized_record_id = _identity(interview_record_id, "interview_record_id")
    _owned_interview_record(db, user_pk, normalized_record_id)
    refs = (
        db.query(InterviewSourceRef)
        .filter(
            InterviewSourceRef.interview_record_id == normalized_record_id,
            InterviewSourceRef.user_id == user_pk,
        )
        .with_for_update()
        .all()
    )
    document_ids = {ref.source_document_id for ref in refs}
    documents = (
        db.query(KnowledgeDocument)
        .filter(
            KnowledgeDocument.id.in_(document_ids),
            KnowledgeDocument.user_id == user_pk,
        )
        .with_for_update()
        .all()
        if document_ids
        else []
    )
    for ref in refs:
        db.delete(ref)
    db.flush()

    deleted_projections = 0
    deleted_file_assets = 0
    ingestion_task_ids: list[str] = []
    for document in documents:
        if document.task_id:
            ingestion_task_ids.append(document.task_id)
        if _projection_has_other_scope(db, document.id):
            continue
        asset = (
            db.get(FileAsset, document.file_asset_id)
            if document.file_asset_id
            else None
        )
        from app.services.knowledge.knowledge_service import (
            delete_document_vectors_and_chunks,
        )

        delete_document_vectors_and_chunks(db, document)
        db.delete(document)
        db.flush()
        deleted_projections += 1
        if asset is not None and not _asset_has_durable_reference(db, asset.id):
            from app.services.uploads.file_asset_service import (
                enqueue_asset_blob_delete,
            )

            enqueue_asset_blob_delete(db, asset)
            db.delete(asset)
            db.flush()
            deleted_file_assets += 1
    return InterviewSourceCleanup(
        source_refs=len(refs),
        deleted_projections=deleted_projections,
        deleted_file_assets=deleted_file_assets,
        ingestion_task_ids=tuple(dict.fromkeys(ingestion_task_ids)),
    )


def load_debrief_source_text(
    db: Session,
    *,
    user_pk: int,
    conversation_id: str,
    source_ref_id: str,
) -> dict[str, object]:
    """Read one selected InterviewRecord source through a sibling Conversation."""

    conversation = _owned_conversation(
        db,
        user_pk,
        _identity(conversation_id, "conversation_id"),
    )
    if (
        conversation.type != "debrief"
        or conversation.subject_type != "interview_record"
        or not conversation.subject_id
    ):
        raise AttachmentSourceNotFoundError(source_ref_id)
    row = (
        db.query(InterviewSourceRef, KnowledgeDocument, FileAsset)
        .join(
            KnowledgeDocument,
            KnowledgeDocument.id == InterviewSourceRef.source_document_id,
        )
        .join(FileAsset, FileAsset.id == InterviewSourceRef.file_asset_id)
        .filter(
            InterviewSourceRef.id == _identity(source_ref_id, "source_ref_id"),
            InterviewSourceRef.user_id == user_pk,
            InterviewSourceRef.interview_record_id == conversation.subject_id,
            InterviewSourceRef.removed_at.is_(None),
        )
        .one_or_none()
    )
    if row is None:
        raise AttachmentSourceNotFoundError(source_ref_id)
    ref, document, asset = row
    if not _promoted_owner_is_valid(ref, document, asset):
        raise AttachmentSourceConflictError("复盘来源身份、版本或原始文件已失效。")
    status = _processing_status(document)
    if status != "ready":
        raise AttachmentSourceConflictError(
            document.error_message or "复盘来源仍在处理或解析失败。"
        )

    from app.models.document_chunk import DocumentChunk

    chunks = (
        db.query(DocumentChunk)
        .filter(
            DocumentChunk.document_id == document.id,
            DocumentChunk.user_id == user_pk,
            DocumentChunk.deleted_at.is_(None),
            DocumentChunk.index_status != "deleted",
        )
        .order_by(DocumentChunk.chunk_index)
        .all()
    )
    content = "\n\n".join(chunk.text for chunk in chunks if chunk.text)
    content = content or document.content_text or ""
    if not content:
        raise AttachmentSourceConflictError("复盘来源没有可读取的解析内容。")
    return {
        "source_ref_id": ref.id,
        "interview_record_id": ref.interview_record_id,
        "file_asset_id": ref.file_asset_id,
        "file_asset_version": ref.file_asset_version,
        "title": ref.display_name,
        "content": content,
        "source": {
            "type": "debrief_project_source",
            "source_ref_id": ref.id,
            "interview_record_id": ref.interview_record_id,
            "file_asset_id": ref.file_asset_id,
            "file_asset_version": ref.file_asset_version,
        },
    }


def _resolve_source_in_conversation(
    db: Session,
    *,
    user_pk: int,
    conversation: Conversation,
    source_id: str,
    for_update: bool,
):
    draft_query = (
        db.query(
            ConversationAttachmentDraft,
            KnowledgeDocument,
            FileAsset,
        )
        .outerjoin(
            KnowledgeDocument,
            KnowledgeDocument.id == ConversationAttachmentDraft.source_document_id,
        )
        .outerjoin(FileAsset, FileAsset.id == ConversationAttachmentDraft.file_asset_id)
    )
    if for_update:
        draft_query = draft_query.with_for_update()
    draft_row = draft_query.filter(
        ConversationAttachmentDraft.id == source_id,
        ConversationAttachmentDraft.user_id == user_pk,
        ConversationAttachmentDraft.conversation_id == conversation.id,
        ConversationAttachmentDraft.removed_at.is_(None),
    ).one_or_none()
    if draft_row is not None:
        return (*draft_row, "draft")

    claimed_query = (
        db.query(
            ConversationAttachmentRef,
            KnowledgeDocument,
            FileAsset,
        )
        .outerjoin(
            KnowledgeDocument,
            KnowledgeDocument.id == ConversationAttachmentRef.source_document_id,
        )
        .outerjoin(FileAsset, FileAsset.id == ConversationAttachmentRef.file_asset_id)
    )
    if for_update:
        claimed_query = claimed_query.with_for_update()
    claimed_row = claimed_query.filter(
        ConversationAttachmentRef.id == source_id,
        ConversationAttachmentRef.user_id == user_pk,
        ConversationAttachmentRef.conversation_id == conversation.id,
        ConversationAttachmentRef.removed_at.is_(None),
    ).one_or_none()
    if claimed_row is not None:
        return (*claimed_row, "conversation_attachment")

    if (
        conversation.type == "debrief"
        and conversation.subject_type == "interview_record"
        and conversation.subject_id
    ):
        promoted_query = (
            db.query(
                InterviewSourceRef,
                KnowledgeDocument,
                FileAsset,
            )
            .outerjoin(
                KnowledgeDocument,
                KnowledgeDocument.id == InterviewSourceRef.source_document_id,
            )
            .outerjoin(FileAsset, FileAsset.id == InterviewSourceRef.file_asset_id)
        )
        if for_update:
            promoted_query = promoted_query.with_for_update()
        promoted_row = promoted_query.filter(
            InterviewSourceRef.id == source_id,
            InterviewSourceRef.user_id == user_pk,
            InterviewSourceRef.interview_record_id == conversation.subject_id,
            InterviewSourceRef.removed_at.is_(None),
        ).one_or_none()
        if promoted_row is not None:
            return (*promoted_row, "debrief_project_source")
    raise AttachmentSourceNotFoundError(source_id)


def _state_from_resolved(db: Session, source) -> AttachmentSourceState:
    owner, document, asset, kind = source
    if kind == "draft":
        return _state_for_draft(
            db,
            owner,
            document,
            asset,
            scope_kind="composer_draft",
            scope_id=owner.conversation_id,
        )
    if kind == "conversation_attachment":
        return _state_for_claimed(db, owner, document, asset)
    return _state_for_promoted(db, owner, document, asset)


def _state_for_draft(
    db: Session,
    draft: ConversationAttachmentDraft,
    document: KnowledgeDocument | None,
    asset: FileAsset | None,
    *,
    scope_kind: AttachmentScopeKind,
    scope_id: str,
) -> AttachmentSourceState:
    reason = _invalid_owner_reason(document, asset)
    if draft.removed_at is not None:
        reason = "附件草稿已移除。"
    status = "failed" if reason else _processing_status(document)
    error = reason or (document.error_message if document else None)
    quality, coverage = _projection_diagnostics(db, document, status=status)
    return AttachmentSourceState(
        source_id=draft.id,
        source_kind="draft",
        scope_kind=scope_kind,
        scope_id=scope_id,
        status=status,
        file_asset_id=draft.file_asset_id,
        file_asset_version=file_asset_version_token(asset) if asset else None,
        document_id=draft.source_document_id,
        title=(
            asset.original_filename
            if asset
            else document.title
            if document
            else draft.id
        ),
        error_message=error,
        can_retry=(
            status == "failed"
            and reason is None
            and draft.removed_at is None
            and document is not None
        ),
        parse_quality=quality,
        coverage=coverage,
    )


def _state_for_claimed(
    db: Session,
    ref: ConversationAttachmentRef,
    document: KnowledgeDocument | None,
    asset: FileAsset | None,
) -> AttachmentSourceState:
    reason = None
    if (
        document is None
        or asset is None
        or not _claimed_owner_is_valid(ref, document, asset)
    ):
        reason = "附件来源身份、版本或原始文件已失效。"
    status = "failed" if reason else _processing_status(document)
    quality, coverage = _projection_diagnostics(db, document, status=status)
    return AttachmentSourceState(
        source_id=ref.id,
        source_kind="conversation_attachment",
        scope_kind="conversation",
        scope_id=ref.conversation_id,
        status=status,
        file_asset_id=ref.file_asset_id,
        file_asset_version=ref.file_asset_version,
        document_id=ref.source_document_id,
        title=ref.display_name,
        error_message=reason or (document.error_message if document else None),
        can_retry=status == "failed" and reason is None,
        parse_quality=quality,
        coverage=coverage,
    )


def _state_for_promoted(
    db: Session,
    ref: InterviewSourceRef,
    document: KnowledgeDocument | None,
    asset: FileAsset | None,
) -> AttachmentSourceState:
    reason = None
    if (
        document is None
        or asset is None
        or not _promoted_owner_is_valid(ref, document, asset)
    ):
        reason = "复盘来源身份、版本或原始文件已失效。"
    status = "failed" if reason else _processing_status(document)
    quality, coverage = _projection_diagnostics(db, document, status=status)
    return AttachmentSourceState(
        source_id=ref.id,
        source_kind="debrief_project_source",
        scope_kind="debrief_project",
        scope_id=ref.interview_record_id,
        status=status,
        file_asset_id=ref.file_asset_id,
        file_asset_version=ref.file_asset_version,
        document_id=ref.source_document_id,
        title=ref.display_name,
        error_message=reason or (document.error_message if document else None),
        can_retry=status == "failed" and reason is None,
        parse_quality=quality,
        coverage=coverage,
    )


def _processing_status(
    document: KnowledgeDocument | None,
) -> AttachmentProcessingStatus:
    if document is None:
        return "failed"
    if document.status in {"processing", "retrying"}:
        return "processing"
    return "ready" if document.status == "ready" else "failed"


def _projection_diagnostics(
    db: Session,
    document: KnowledgeDocument | None,
    *,
    status: AttachmentProcessingStatus,
) -> tuple[dict[str, object], dict[str, object]]:
    """Project persisted parser metadata into stable, truthful UI fields."""

    chunks = (
        db.query(DocumentChunk)
        .filter(
            DocumentChunk.document_id == document.id,
            DocumentChunk.deleted_at.is_(None),
            DocumentChunk.index_status != "deleted",
        )
        .order_by(DocumentChunk.chunk_index)
        .all()
        if document is not None
        else []
    )
    metadata: dict[str, object] = {}
    for chunk in chunks:
        try:
            candidate = json.loads(chunk.metadata_json or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(candidate, dict):
            metadata = candidate
            break
    parser_profile = metadata.get("parser_profile")
    parser_profile = parser_profile if isinstance(parser_profile, dict) else {}
    cleaning_profile = metadata.get("cleaning_profile")
    cleaning_profile = cleaning_profile if isinstance(cleaning_profile, dict) else {}
    warnings: list[str] = []
    for value in (
        parser_profile.get("warnings"),
        parser_profile.get("quality_warnings"),
        cleaning_profile.get("warnings"),
    ):
        if isinstance(value, list):
            warnings.extend(str(item) for item in value if str(item).strip())
    page_starts = [int(chunk.page_start) for chunk in chunks if chunk.page_start]
    page_ends = [int(chunk.page_end) for chunk in chunks if chunk.page_end]
    parsed_chars = parser_profile.get("char_count")
    if not isinstance(parsed_chars, int):
        parsed_chars = len(document.content_text or "") if document else 0
    page_count = parser_profile.get("page_count")
    if not isinstance(page_count, int):
        page_count = None
    quality_score = parser_profile.get("quality_score")
    if not isinstance(quality_score, (int, float)):
        quality_score = None
    return (
        {
            "parser_id": str(metadata.get("parser_id"))
            if metadata.get("parser_id")
            else None,
            "quality_score": float(quality_score)
            if quality_score is not None
            else None,
            "ocr_used": bool(metadata.get("ocr_used")),
            "warnings": list(dict.fromkeys(warnings)),
        },
        {
            "chunk_count": len(chunks),
            "parsed_char_count": max(0, int(parsed_chars)),
            "page_count": page_count,
            "page_start": min(page_starts) if page_starts else None,
            "page_end": max(page_ends) if page_ends else None,
            "full_text_projection_available": bool(
                status == "ready" and (chunks or (document and document.content_text))
            ),
            # Text/OCR extraction alone never proves that visual layout was
            # inspected.  A future page-vision flow may set a separate receipt.
            "visual_layout_reviewed": False,
        },
    )


def _invalid_owner_reason(
    document: KnowledgeDocument | None,
    asset: FileAsset | None,
) -> str | None:
    if document is None:
        return "附件解析投影已不存在。"
    if document.deleted_at is not None:
        return "附件解析投影已删除。"
    if not _asset_is_readable(asset):
        return "附件原始文件当前不可用。"
    if document.file_asset_id != asset.id or document.source_kind != "chat_attachment":
        return "附件来源所有权不一致。"
    return None


def _claimed_owner_is_valid(
    ref: ConversationAttachmentRef,
    document: KnowledgeDocument,
    asset: FileAsset,
) -> bool:
    return bool(
        ref.source_document_id == document.id
        and ref.file_asset_id == asset.id
        and document.file_asset_id == asset.id
        and document.source_kind == "chat_attachment"
        and document.deleted_at is None
        and _asset_is_readable(asset)
        and ref.file_asset_version == file_asset_version_token(asset)
        and ref.removed_at is None
    )


def _promoted_owner_is_valid(
    ref: InterviewSourceRef,
    document: KnowledgeDocument,
    asset: FileAsset,
) -> bool:
    return bool(
        ref.source_document_id == document.id
        and ref.file_asset_id == asset.id
        and document.file_asset_id == asset.id
        and document.source_kind == "chat_attachment"
        and document.deleted_at is None
        and _asset_is_readable(asset)
        and ref.file_asset_version == file_asset_version_token(asset)
        and ref.removed_at is None
    )


def _asset_is_readable(asset: FileAsset | None) -> bool:
    return bool(
        asset is not None
        and asset.deleted_at is None
        and asset.upload_status in {"uploaded", "consumed"}
        and asset.validation_status == "passed"
    )


def _projection_has_other_scope(db: Session, document_id: str) -> bool:
    return bool(
        db.query(InterviewSourceRef.id)
        .filter(InterviewSourceRef.source_document_id == document_id)
        .first()
        or db.query(ConversationAttachmentRef.id)
        .filter(ConversationAttachmentRef.source_document_id == document_id)
        .first()
        or db.query(ConversationAttachmentDraft.id)
        .filter(
            ConversationAttachmentDraft.source_document_id == document_id,
            ConversationAttachmentDraft.removed_at.is_(None),
        )
        .first()
    )


def _asset_has_durable_reference(db: Session, file_asset_id: str) -> bool:
    """Conservatively protect every known formal/raw-file owner."""

    if (
        db.query(InterviewSourceRef.id)
        .filter(
            InterviewSourceRef.file_asset_id == file_asset_id,
            InterviewSourceRef.removed_at.is_(None),
        )
        .first()
        or db.query(KnowledgeDocument.id)
        .filter(
            KnowledgeDocument.file_asset_id == file_asset_id,
            KnowledgeDocument.deleted_at.is_(None),
        )
        .first()
        or db.query(ConversationAttachmentRef.id)
        .filter(ConversationAttachmentRef.file_asset_id == file_asset_id)
        .first()
        or db.query(ConversationAttachmentDraft.id)
        .filter(
            ConversationAttachmentDraft.file_asset_id == file_asset_id,
            ConversationAttachmentDraft.removed_at.is_(None),
        )
        .first()
    ):
        return True

    # Imports remain local so this Stage-1 service does not create model-layer
    # dependencies; these are direct real owners, not a source registry.
    from app.models.artifact import ArtifactVersion
    from app.models.interview_qa import InterviewQA
    from app.models.resume import Resume

    return bool(
        db.query(ArtifactVersion.id)
        .filter(ArtifactVersion.file_asset_id == file_asset_id)
        .first()
        or db.query(Resume.id).filter(Resume.file_asset_id == file_asset_id).first()
        or db.query(InterviewRecord.id)
        .filter(
            or_(
                InterviewRecord.audio_file_asset_id == file_asset_id,
                InterviewRecord.resume_file_asset_id == file_asset_id,
                InterviewRecord.jd_file_asset_id == file_asset_id,
            )
        )
        .first()
        or db.query(InterviewQA.id)
        .filter(InterviewQA.answer_audio_file_asset_id == file_asset_id)
        .first()
    )


def _owned_conversation(
    db: Session,
    user_pk: int,
    conversation_id: str,
    *,
    include_archived: bool = False,
) -> Conversation:
    query = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.user_id == user_pk,
    )
    if not include_archived:
        query = query.filter(Conversation.archived_at.is_(None))
    conversation = query.one_or_none()
    if conversation is None:
        raise AttachmentSourceNotFoundError(conversation_id)
    return conversation


def _owned_interview_record(
    db: Session,
    user_pk: int,
    interview_record_id: str,
) -> InterviewRecord:
    record = (
        db.query(InterviewRecord)
        .filter(
            InterviewRecord.id == interview_record_id,
            InterviewRecord.user_id == user_pk,
        )
        .one_or_none()
    )
    if record is None:
        raise AttachmentSourceNotFoundError(interview_record_id)
    return record


def _draft_ids(items) -> list[str]:
    return [
        str(item["draft_id"])
        for item in items
        if isinstance(item, dict) and str(item.get("draft_id") or "").strip()
    ]


def _missing_state(
    *,
    source_id: str,
    source_kind: AttachmentSourceKind,
    scope_kind: AttachmentScopeKind,
    scope_id: str,
    reason: str,
) -> AttachmentSourceState:
    return AttachmentSourceState(
        source_id=source_id,
        source_kind=source_kind,
        scope_kind=scope_kind,
        scope_id=scope_id,
        status="failed",
        file_asset_id=None,
        file_asset_version=None,
        document_id=None,
        title=source_id,
        error_message=reason,
        can_retry=False,
        parse_quality={
            "parser_id": None,
            "quality_score": None,
            "ocr_used": False,
            "warnings": [],
        },
        coverage={
            "chunk_count": 0,
            "parsed_char_count": 0,
            "page_count": None,
            "page_start": None,
            "page_end": None,
            "full_text_projection_available": False,
            "visual_layout_reviewed": False,
        },
    )


def _identity(value: str, field: str) -> str:
    normalized = (value or "").strip()
    if not normalized or len(normalized) > 128:
        raise AttachmentSourceCommandError(field)
    return normalized


__all__ = [
    "AttachmentProjectionRetry",
    "AttachmentSourceCommandError",
    "AttachmentSourceConflictError",
    "AttachmentSourceNotFoundError",
    "AttachmentSourceState",
    "ConversationAttachmentCleanup",
    "InterviewSourceCleanup",
    "cleanup_conversation_attachment_scope",
    "cleanup_interview_source_scope",
    "get_attachment_source_state",
    "list_claimed_attachment_sources",
    "list_debrief_project_sources",
    "list_pending_submission_sources",
    "load_debrief_source_text",
    "mark_attachment_retry_dispatch_failed",
    "prepare_attachment_projection_retry",
    "promote_attachment_to_debrief",
    "remove_conversation_attachment_from_scope",
    "remove_debrief_project_source",
]
