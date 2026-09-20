"""Snapshots that fence parser/embedding results against concurrent source edits."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import database
from app.models.knowledge import KnowledgeDocument
from app.files.identity import file_asset_version_token
from app.models.file_asset import FileAsset


class IndexSourceChanged(RuntimeError):
    """Prepared output is stale, not a reason to overwrite current source facts."""


@dataclass(frozen=True)
class SourceSnapshot:
    document_id: str
    user_id: int
    source_kind: str
    title: str | None
    revision: str


def source_snapshot(db: Session, doc: KnowledgeDocument) -> SourceSnapshot:
    if doc.deleted_at is not None or doc.status in {"deleting", "deleted", "stale"}:
        raise IndexSourceChanged("source is no longer indexable")
    asset = db.get(FileAsset, doc.file_asset_id) if doc.file_asset_id else None
    if doc.file_asset_id and (
        asset is None
        or asset.user_id != doc.user_id
        or asset.deleted_at is not None
        or asset.upload_status not in {"uploaded", "consumed"}
    ):
        raise PermissionError("source file ownership mismatch")
    state = [
        doc.id,
        doc.user_id,
        doc.source_kind,
        doc.title,
        doc.content_text,
        doc.source_ref_type,
        doc.source_ref_id,
        doc.source_interview_record_id,
        doc.task_id,
        doc.file_asset_id,
        file_asset_version_token(asset) if asset is not None else None,
    ]
    revision = hashlib.sha256(
        json.dumps(state, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    return SourceSnapshot(doc.id, doc.user_id, doc.source_kind, doc.title, revision)


def capture_source(document_id: str, user_id: int, source_kind: str) -> SourceSnapshot:
    with database.SessionLocal() as db:
        doc = db.scalar(
            select(KnowledgeDocument).where(KnowledgeDocument.id == document_id)
        )
        if doc is None:
            raise IndexSourceChanged("canonical source document does not exist")
        if doc.user_id != user_id or doc.source_kind != source_kind:
            raise PermissionError("canonical source ownership/type mismatch")
        return source_snapshot(db, doc)
