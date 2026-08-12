"""Validation and durable snapshots for user-turn file attachments."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session, selectinload

from app.models.knowledge import KnowledgeDocument


class AttachmentNotFoundError(ValueError):
    pass


class AttachmentNotReadyError(ValueError):
    def __init__(self, document_id: str, title: str, status: str):
        self.document_id = document_id
        self.title = title
        self.status = status
        super().__init__(f"attachment {document_id} is {status}")


@dataclass(frozen=True)
class ResolvedAttachment:
    document_id: str
    title: str
    source_kind: str
    file_asset_id: str | None

    def snapshot(self) -> dict[str, str | None]:
        return {
            "document_id": self.document_id,
            "title": self.title,
            "source_kind": self.source_kind,
            "file_asset_id": self.file_asset_id,
        }

    def message_block(self) -> dict[str, str]:
        return {
            "type": "attachment",
            "document_id": self.document_id,
            "title": self.title,
            "source_kind": self.source_kind,
        }


def resolve_turn_attachments(
    db: Session,
    *,
    user_pk: int,
    session_id: str,
    document_ids: list[str],
) -> list[ResolvedAttachment]:
    """Resolve untrusted IDs to ready, owner-scoped server records."""
    ordered_ids = list(dict.fromkeys(value.strip() for value in document_ids if value.strip()))
    if not ordered_ids:
        return []

    rows = (
        db.query(KnowledgeDocument)
        .options(selectinload(KnowledgeDocument.upload))
        .filter(
            KnowledgeDocument.id.in_(ordered_ids),
            KnowledgeDocument.user_id == user_pk,
            KnowledgeDocument.deleted_at.is_(None),
        )
        .all()
    )
    by_id = {
        row.id: row
        for row in rows
        if row.source_kind != "chat_attachment"
        or row.conversation_id == session_id
    }
    missing = [document_id for document_id in ordered_ids if document_id not in by_id]
    if missing:
        raise AttachmentNotFoundError(missing[0])

    resolved: list[ResolvedAttachment] = []
    for document_id in ordered_ids:
        row = by_id[document_id]
        if row.status != "ready":
            raise AttachmentNotReadyError(row.id, row.title, row.status)
        resolved.append(
            ResolvedAttachment(
                document_id=row.id,
                title=row.title,
                source_kind=row.source_kind,
                file_asset_id=row.file_asset_id,
            )
        )
    return resolved


def attachment_message_blocks(
    attachments: list[ResolvedAttachment], message: str
) -> list[dict]:
    return [
        *(attachment.message_block() for attachment in attachments),
        {"type": "text", "text": message},
    ]


__all__ = [
    "AttachmentNotFoundError",
    "AttachmentNotReadyError",
    "ResolvedAttachment",
    "attachment_message_blocks",
    "resolve_turn_attachments",
]
