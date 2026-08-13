"""Explicit ConversationAttachmentRef -> Artifact scope promotion.

This focused Application Service creates a new formal Artifact owner while
reusing the exact immutable FileAsset identity admitted to the Conversation.
It never copies parsed text and never mutates or removes the Conversation
AttachmentRef.  Resume promotion delegates to the canonical resume aggregate,
which produces reviewable profile candidates only after asynchronous parsing.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.artifact import Artifact, ArtifactVersion
from app.models.chat import Conversation
from app.models.conversation_attachment import ConversationAttachmentRef
from app.models.file_asset import FileAsset
from app.models.knowledge import KnowledgeDocument
from app.schemas.artifact import ArtifactProvenanceInput, ArtifactWriteInput
from app.services import artifact_service
from app.services.chat.attachment_source_service import (
    AttachmentSourceConflictError,
    AttachmentSourceNotFoundError,
)
from app.services.resume import resume_artifact_service
from app.services.uploads.file_asset_service import (
    file_asset_version_token,
    mark_file_asset_consumed,
)


@dataclass(frozen=True)
class AttachmentArtifactPromotion:
    source_ref_id: str
    file_asset_id: str
    file_asset_version: str
    artifact: Artifact
    current_version: ArtifactVersion
    resume_record: resume_artifact_service.ResumeArtifactRecord | None


def promote_conversation_attachment_to_artifact(
    db: Session,
    *,
    user_pk: int,
    conversation_id: str,
    attachment_ref_id: str,
    operation_key: str,
    artifact_kind: str,
    title: str,
) -> AttachmentArtifactPromotion:
    """Grant a formal Artifact scope to one exact owned Conversation file.

    The caller owns the transaction and must dispatch resume parsing only after
    commit.  Stable ``operation_key`` replay returns the same Artifact when the
    complete frozen payload matches; a changed payload is rejected by the
    canonical Artifact service.
    """

    normalized_conversation_id = _identity(conversation_id, "conversation_id")
    normalized_ref_id = _identity(attachment_ref_id, "attachment_ref_id")
    source = (
        db.query(
            ConversationAttachmentRef,
            KnowledgeDocument,
            FileAsset,
        )
        .join(
            Conversation,
            Conversation.id == ConversationAttachmentRef.conversation_id,
        )
        .join(
            KnowledgeDocument,
            KnowledgeDocument.id == ConversationAttachmentRef.source_document_id,
        )
        .join(FileAsset, FileAsset.id == ConversationAttachmentRef.file_asset_id)
        .filter(
            ConversationAttachmentRef.id == normalized_ref_id,
            ConversationAttachmentRef.user_id == user_pk,
            ConversationAttachmentRef.conversation_id == normalized_conversation_id,
            ConversationAttachmentRef.removed_at.is_(None),
            Conversation.user_id == user_pk,
            Conversation.archived_at.is_(None),
        )
        .with_for_update()
        .one_or_none()
    )
    if source is None:
        raise AttachmentSourceNotFoundError(normalized_ref_id)
    ref, document, asset = source
    if not _source_identity_is_current(ref, document, asset):
        raise AttachmentSourceConflictError("附件来源身份、冻结版本或原始文件已失效。")

    provenance = ArtifactProvenanceInput(
        source_turn_id=ref.turn_id,
        source_owner_type="conversation_attachment_ref",
        source_owner_id=ref.id,
    )
    normalized_kind = (artifact_kind or "").strip().casefold()
    resume_record = None
    if normalized_kind == "resume":
        resume_record = resume_artifact_service.create_resume_artifact(
            db,
            user_pk=user_pk,
            operation_key=operation_key,
            title=title,
            file_asset_id=ref.file_asset_id,
            file_asset_version=ref.file_asset_version,
            raw_text=None,
            make_default=None,
            content_format="source_file",
            provenance=provenance,
            source_owner_checker=_attachment_ref_owner_checker,
        )
        artifact = resume_record.artifact
        current_version = resume_record.current_version
    else:
        artifact = artifact_service.save_artifact_explicitly(
            db,
            user_pk=user_pk,
            operation_key=operation_key,
            artifact_kind=artifact_kind,
            version=ArtifactWriteInput(
                title=title,
                content_text=None,
                content_format="source_file",
                file_asset_id=ref.file_asset_id,
                file_asset_version=ref.file_asset_version,
                provenance=provenance,
            ),
            source_owner_checker=_attachment_ref_owner_checker,
        )
        current_version = artifact_service.get_current_artifact_version(
            db,
            user_pk=user_pk,
            artifact_id=artifact.id,
        )

    mark_file_asset_consumed(db, asset)
    db.flush()
    return AttachmentArtifactPromotion(
        source_ref_id=ref.id,
        file_asset_id=ref.file_asset_id,
        file_asset_version=ref.file_asset_version,
        artifact=artifact,
        current_version=current_version,
        resume_record=resume_record,
    )


def _attachment_ref_owner_checker(
    db: Session,
    user_pk: int,
    owner_type: str,
    owner_id: str,
) -> bool:
    """Validate only the concrete AttachmentRef owner used by this command."""

    if owner_type != "conversation_attachment_ref":
        return False
    source = (
        db.query(
            ConversationAttachmentRef,
            KnowledgeDocument,
            FileAsset,
        )
        .join(
            KnowledgeDocument,
            KnowledgeDocument.id == ConversationAttachmentRef.source_document_id,
        )
        .join(FileAsset, FileAsset.id == ConversationAttachmentRef.file_asset_id)
        .filter(
            ConversationAttachmentRef.id == owner_id,
            ConversationAttachmentRef.user_id == user_pk,
            ConversationAttachmentRef.removed_at.is_(None),
        )
        .one_or_none()
    )
    return source is not None and _source_identity_is_current(*source)


def _source_identity_is_current(
    ref: ConversationAttachmentRef,
    document: KnowledgeDocument,
    asset: FileAsset,
) -> bool:
    return bool(
        ref.source_document_id == document.id
        and ref.file_asset_id == asset.id
        and document.user_id == ref.user_id
        and document.file_asset_id == asset.id
        and document.source_kind == "chat_attachment"
        and document.deleted_at is None
        and asset.user_id == ref.user_id
        and asset.deleted_at is None
        and asset.upload_status in {"uploaded", "consumed"}
        and asset.validation_status == "passed"
        and ref.file_asset_version == file_asset_version_token(asset)
    )


def _identity(value: str, field: str) -> str:
    normalized = (value or "").strip()
    if not normalized or len(normalized) > 128:
        raise AttachmentSourceConflictError(field)
    return normalized


__all__ = [
    "AttachmentArtifactPromotion",
    "promote_conversation_attachment_to_artifact",
]
