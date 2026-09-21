"""Conservative migration boundary for legacy Conversation attachments.

The retired implementation treated ``KnowledgeDocument(source_kind=
"chat_attachment")`` plus ``conversation_id`` as Conversation scope.  That
pair does not identify an accepted user submission, Turn, order, or immutable
file version, so it is not sufficient to create a canonical
``ConversationAttachmentRef``.

This operational helper therefore does only two things:

* reports documents that already have a canonical draft/ref or an explicit
  Debrief source grant; and
* optionally soft-quarantines orphan/provisional projections while retaining
  the underlying ``FileAsset`` for an explicit user re-attachment or
  promotion.

It never manufactures History, a Turn, a Submission, or a scope grant.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.types import utc_now
from app.models.chat import Conversation
from app.models.conversation_attachment import (
    ConversationAttachmentDraft,
    ConversationAttachmentRef,
)
from app.models.file_asset import FileAsset
from app.models.interview_source import InterviewSourceRef
from app.models.knowledge import KnowledgeDocument


def migrate_legacy_attachments(
    db: Session,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Classify legacy attachment projections and optionally quarantine them.

    The caller owns commit/rollback.  ``apply=False`` is a deterministic
    dry-run.  Applying the report only sets ``KnowledgeDocument.deleted_at``
    on rows with no canonical owner; bytes and FileAsset identity are kept.
    """

    items: list[dict[str, Any]] = []
    documents = (
        db.query(KnowledgeDocument)
        .filter(KnowledgeDocument.source_kind == "chat_attachment")
        .order_by(KnowledgeDocument.id.asc())
        .all()
    )
    for document in documents:
        canonical = _canonical_targets(db, document.id)
        if canonical:
            items.append(
                _item(
                    document,
                    classification="already_migrated",
                    reason=(
                        "canonical scope identity already exists; the legacy "
                        "projection is only parsed-content storage"
                    ),
                    canonical_targets=canonical,
                )
            )
            continue

        if document.deleted_at is not None:
            items.append(
                _item(
                    document,
                    classification="already_quarantined",
                    reason=(
                        "legacy projection is already soft-deleted and grants "
                        "no Conversation or Debrief scope"
                    ),
                )
            )
            continue

        validation_reason = _validation_reason(db, document)
        reason = (
            validation_reason
            or "no persisted AttachmentRef identifies an accepted Turn/submission"
        )
        if apply:
            document.deleted_at = utc_now()
            classification = "quarantined"
        else:
            classification = "quarantine_required"
        items.append(
            _item(
                document,
                classification=classification,
                reason=(
                    f"{reason}; retain FileAsset bytes and require explicit "
                    "user re-attachment or promotion"
                ),
            )
        )

    counts: dict[str, int] = {}
    for item in items:
        key = str(item["classification"])
        counts[key] = counts.get(key, 0) + 1
    return {"applied": apply, "counts": counts, "items": items}


def _canonical_targets(db: Session, document_id: str) -> list[dict[str, str]]:
    targets: list[dict[str, str]] = []
    drafts = (
        db.query(ConversationAttachmentDraft)
        .filter(ConversationAttachmentDraft.source_document_id == document_id)
        .order_by(ConversationAttachmentDraft.id.asc())
        .all()
    )
    targets.extend(
        {"kind": "conversation_attachment_draft", "id": row.id} for row in drafts
    )
    refs = (
        db.query(ConversationAttachmentRef)
        .filter(ConversationAttachmentRef.source_document_id == document_id)
        .order_by(ConversationAttachmentRef.id.asc())
        .all()
    )
    targets.extend(
        {"kind": "conversation_attachment_ref", "id": row.id} for row in refs
    )
    project_refs = (
        db.query(InterviewSourceRef)
        .filter(InterviewSourceRef.source_document_id == document_id)
        .order_by(InterviewSourceRef.id.asc())
        .all()
    )
    targets.extend(
        {"kind": "interview_source_ref", "id": row.id} for row in project_refs
    )
    return targets


def _validation_reason(db: Session, document: KnowledgeDocument) -> str | None:
    if not document.conversation_id:
        return "missing legacy conversation identity"
    conversation = db.get(Conversation, document.conversation_id)
    if conversation is None:
        return "legacy conversation no longer exists"
    if conversation.user_id != document.user_id:
        return "legacy conversation owner does not match document owner"
    if not document.file_asset_id:
        return "missing FileAsset identity"
    asset = db.get(FileAsset, document.file_asset_id)
    if asset is None:
        return "FileAsset no longer exists"
    if asset.user_id != document.user_id:
        return "FileAsset owner does not match document owner"
    return None


def _item(
    document: KnowledgeDocument,
    *,
    classification: str,
    reason: str,
    canonical_targets: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "source_kind": "legacy_chat_attachment_projection",
        "source_id": document.id,
        "user_id": document.user_id,
        "conversation_id": document.conversation_id,
        "file_asset_id": document.file_asset_id,
        "classification": classification,
        "canonical_targets": canonical_targets or [],
        "reason": reason,
    }


__all__ = ["migrate_legacy_attachments"]
