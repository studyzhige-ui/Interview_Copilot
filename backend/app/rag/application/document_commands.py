"""Owned knowledge mutations; HTTP and Agent adapters do not write these rows."""

import logging
from sqlalchemy.orm import Session
from app.core.command_errors import CommandError
from app.core.error_messages import humanize_error
from app.models.knowledge import KnowledgeDocument
from app.models.user import User
from app.schemas.rag import (
    KnowledgeDocumentCreateRequest,
    KnowledgeDocumentUpdateRequest,
)
from app.rag.application.library.document_formats import UnsupportedDocumentFormat
from app.rag.application.library.document_formats import (
    validate_knowledge_document_format,
)
from app.rag.application.library.knowledge_service import default_title
from app.files.application.file_asset_service import get_owned_file_asset
from app.files.application.file_asset_service import ensure_uploaded
from app.files.application.file_asset_service import mark_file_asset_consumed
from app.files.application.file_asset_service import UPLOAD_STATUS_CONSUMED
from app.files.application.file_asset_service import UPLOAD_STATUS_UPLOADED
from app.task_queue.dispatch import dispatch_document_ingestion

logger = logging.getLogger(__name__)


def create_document(
    db: Session,
    *,
    current_user: User,
    body: KnowledgeDocumentCreateRequest,
    dispatch=None,
):
    dispatch = dispatch or dispatch_document_ingestion
    try:
        upload = get_owned_file_asset(
            db,
            file_asset_id=body.upload_id,
            user_id=current_user.username,
            purpose="knowledge_document",
            for_update=True,
        )
        if upload is None:
            raise CommandError(kind="not_found", message="Upload not found")
        if upload.upload_status == UPLOAD_STATUS_CONSUMED:
            raise CommandError(
                kind="conflict", message="Upload has already been consumed"
            )
        # Confirm-on-consume (UP-1): verification (exists / size cap / magic)
        # can't be skipped by never calling /confirm.
        upload = ensure_uploaded(db, upload)
        if upload.upload_status != UPLOAD_STATUS_UPLOADED:
            raise CommandError(
                "invalid", f"文档校验未通过：{upload.validation_error or '上传未完成'}"
            )

        # Format whitelist (ingestion §4.1.2) — the authoritative gate. The
        # bytes never traverse the API (presigned upload), so this checks the
        # declared extension/content_type before any worker work is dispatched.
        try:
            validate_knowledge_document_format(
                upload.original_filename, upload.content_type
            )
        except UnsupportedDocumentFormat as exc:
            raise CommandError(kind="invalid", message=str(exc)) from exc

        document = KnowledgeDocument(
            user_id=current_user.id,
            conversation_id=None,
            file_asset_id=upload.id,
            title=body.title or default_title(upload),
            category=body.category.strip() or "默认",
            source_kind=body.source_kind.value,
            storage_uri=upload.storage_uri,
            object_key=upload.object_key,
            status="processing",
        )
        db.add(document)
        mark_file_asset_consumed(db, upload)
        # Commit before dispatch. A flush is not visible to the Celery worker,
        # so dispatching between flush and commit races with a fast worker that
        # queries the document from another database connection.
        db.flush()
        document_id = document.id
        db.commit()
        db.refresh(document)

        try:
            task = dispatch(document_id)
        except Exception as exc:  # noqa: BLE001
            # The document is already durable and visible. Park it in a
            # terminal state so a broker outage cannot leave a zombie.
            logger.error("Celery dispatch failed for document %s: %s", document_id, exc)
            document.status = "failed"
            document.error_message = "后台处理队列暂时不可用，请稍后重试。"
            db.commit()
            raise CommandError(
                kind="unavailable",
                message="后台处理队列暂时不可用，请稍后重试",
            ) from exc

        document.task_id = task.id
        db.commit()
        db.refresh(document)

        return document, task.id
    except CommandError:
        raise
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.error("Ingestion API dispatch error: %s", exc)
        raise CommandError(
            kind="failed",
            message=humanize_error(exc),
        ) from exc


def update_document(
    db: Session,
    *,
    document_id: str,
    request: KnowledgeDocumentUpdateRequest,
    current_user: User,
):
    document = (
        db.query(KnowledgeDocument)
        .filter(
            KnowledgeDocument.id == document_id,
            KnowledgeDocument.user_id == current_user.id,
            KnowledgeDocument.source_kind != "chat_attachment",
            KnowledgeDocument.deleted_at.is_(None),
        )
        .populate_existing()
        .with_for_update()
        .first()
    )
    if document is None:
        raise CommandError(kind="not_found", message="Knowledge document not found")
    title_changed = False
    if request.title is not None:
        new_title = request.title.strip() or document.title
        title_changed = new_title != document.title
        document.title = new_title
    if request.category is not None:
        document.category = request.category.strip() or "默认"
    db.add(document)
    if (
        title_changed
        and document.status == "ready"
        and document.source_kind != "chat_attachment"
    ):
        # The title is part of the retrieval passage. Publish its new index view
        # through the same durable outbox as every other external-index update.
        from app.rag.application.library.index_jobs import enqueue_retrieval_upsert

        enqueue_retrieval_upsert(
            db,
            user_pk=document.user_id,
            document_id=document.id,
        )
    db.commit()
    db.refresh(document)
    return document


def record_ingestion_dispatch(db, *, document_id, task_id=None, error=None, now=None):
    """Update a projection only while it is still pending, never undo a worker result.

    This is an internal persistence seam after an owned source was authorized.
    It does not dispatch, retry or grant access based on an arbitrary document ID.
    """
    from app.models.knowledge import KnowledgeDocument

    row = (
        db.query(KnowledgeDocument)
        .filter(KnowledgeDocument.id == document_id)
        .with_for_update()
        .populate_existing()
        .first()
    )
    if row is None:
        raise CommandError("not_found", "Attachment projection missing")
    if row.deleted_at is None and row.status in {"pending", "processing"}:
        if error is not None:
            row.status, row.error_message = "failed", error
        elif task_id is not None:
            row.task_id = task_id
        if now is not None:
            row.updated_at = now
    db.flush()
    return row
