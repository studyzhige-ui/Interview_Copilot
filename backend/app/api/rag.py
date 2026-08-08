import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.api.file_assets import require_uploaded, upload_too_large_http
from app.core.edition import current_edition_policy
from app.core.error_messages import humanize_error
from app.core.rate_limit import RATE_EXPENSIVE, RATE_UPLOAD, limiter
from app.core.security import get_current_user
from app.db.database import get_db
from app.models.knowledge import KnowledgeDocument
from app.models.user import User
from app.rag.contracts import SearchIntent
from app.rag.retriever import query_knowledge_base
from app.rag.runtime import ensure_rag_runtime
from app.schemas.rag import (
    KnowledgeDocumentCreateRequest,
    KnowledgeDocumentUpdateRequest,
    KnowledgeUploadRequest,
    QueryRequest,
    SourceKindEnum,
)
from app.services.knowledge.document_formats import (
    UnsupportedDocumentFormat,
    validate_knowledge_document_format,
)
from app.services.knowledge.knowledge_service import (
    default_title,
    hard_delete_knowledge_document,
)
from app.services.uploads.file_asset_service import (
    UPLOAD_STATUS_CONSUMED,
    UploadTooLarge,
    create_file_asset,
    get_owned_file_asset,
    mark_file_asset_consumed,
)
from app.task_queue.dispatch import dispatch_document_ingestion

logger = logging.getLogger(__name__)

router = APIRouter(tags=["rag"])


@router.post("/rag/query")
@limiter.limit(RATE_EXPENSIVE)
async def api_query_knowledge_base(
    request: Request,
    response: Response,
    body: QueryRequest,
    current_user: User = Depends(get_current_user),
):
    """Execute a user-scoped RAG query against the configured vector store.

    Diagnostic endpoint: returns the hydrated chunks + structured
    retrieval_state. ``[K#]`` numbering / final sources are NOT produced
    here — context assembly owns those on the chat path. The endpoint is a
    Community/developer surface and is deliberately absent in Cloud.
    """
    if not current_edition_policy().expose_rag_diagnostics:
        raise HTTPException(status_code=404, detail="Not found")
    try:
        await asyncio.to_thread(
            ensure_rag_runtime,
            embedding=True,
            reranker=True,
        )
        source_kind_val = body.source_kind.value if body.source_kind else None

        result = await query_knowledge_base(
            intents=[SearchIntent.from_query(body.query)],
            source_kind=source_kind_val,
            user_id=current_user.username,
        )

        return {
            "status": "success",
            "data": {
                "chunks": result.chunks,
                "retrieval_state": result.state.to_dict(),
            },
        }
    except Exception as exc:  # noqa: BLE001
        logger.error("RAG query API failed: %s", exc)
        raise HTTPException(status_code=500, detail=humanize_error(exc)) from exc


def _document_payload(document: KnowledgeDocument) -> dict:
    # Pull file metadata off the related FileAsset row if it loaded with the
    # document (SQLAlchemy lazy-loads when accessed).
    upload = document.upload
    content_type = upload.content_type if upload else None
    size_bytes = upload.size_bytes if upload else None
    return {
        "id": document.id,
        "upload_id": document.file_asset_id,
        "title": document.title,
        "category": document.category,
        "source_kind": document.source_kind,
        "status": document.status,
        "task_id": document.task_id,
        "chunk_count": document.chunk_count,
        "content_type": content_type,
        "size_bytes": size_bytes,
        "error_message": document.error_message,
        "created_at": document.created_at.isoformat() if document.created_at else None,
        "updated_at": document.updated_at.isoformat() if document.updated_at else None,
    }


@router.post("/knowledge/upload/url")
@limiter.limit(RATE_UPLOAD)
def create_knowledge_upload_url(
    request: Request,
    response: Response,
    body: KnowledgeUploadRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create an owned knowledge upload and return a presigned upload URL.

    Size cap comes from PURPOSE_REGISTRY inside ``create_file_asset`` — this
    entry used to skip the declared-size check the file-assets API ran (UP-4).
    """
    try:
        upload, url_info = create_file_asset(
            db,
            user_id=current_user.username,
            filename=body.filename,
            purpose="knowledge_document",
            content_type=body.content_type,
            size_bytes=body.size_bytes,
        )
    except UploadTooLarge as exc:
        raise upload_too_large_http(exc)
    return {
        "status": "success",
        "upload_id": upload.id,
        "upload_url": url_info["upload_url"],
        "filename": upload.original_filename,
    }


@router.post("/knowledge/documents")
@limiter.limit(RATE_UPLOAD)
def create_knowledge_document(
    request: Request,
    response: Response,
    body: KnowledgeDocumentCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        upload = get_owned_file_asset(
            db,
            file_asset_id=body.upload_id,
            user_id=current_user.username,
            purpose="knowledge_document",
        )
        if upload is None:
            raise HTTPException(status_code=404, detail="Upload not found")
        if upload.upload_status == UPLOAD_STATUS_CONSUMED:
            raise HTTPException(
                status_code=409, detail="Upload has already been consumed"
            )
        # Confirm-on-consume (UP-1): verification (exists / size cap / magic)
        # can't be skipped by never calling /confirm.
        upload = require_uploaded(db, upload, "文档")

        # Format whitelist (ingestion §4.1.2) — the authoritative gate. The
        # bytes never traverse the API (presigned upload), so this checks the
        # declared extension/content_type before any worker work is dispatched.
        try:
            validate_knowledge_document_format(
                upload.original_filename, upload.content_type
            )
        except UnsupportedDocumentFormat as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        document = KnowledgeDocument(
            user_id=current_user.id,
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
            task = dispatch_document_ingestion(document_id)
        except Exception as exc:  # noqa: BLE001
            # The document is already durable and visible. Park it in a
            # terminal state so a broker outage cannot leave a zombie.
            logger.error("Celery dispatch failed for document %s: %s", document_id, exc)
            document.status = "failed"
            document.error_message = "后台处理队列暂时不可用，请稍后重试。"
            db.commit()
            raise HTTPException(
                status_code=503,
                detail="后台处理队列暂时不可用，请稍后重试",
            ) from exc

        document.task_id = task.id
        db.commit()
        db.refresh(document)

        return {
            "status": document.status,
            "document": _document_payload(document),
            "task_id": task.id,
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.error("Ingestion API dispatch error: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=humanize_error(exc),
        ) from exc


@router.get("/knowledge/documents")
def list_knowledge_documents(
    category: Optional[str] = None,
    status: Optional[str] = None,
    source_kind: Optional[SourceKindEnum] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # selectinload(.upload) avoids an N+1 in ``_document_payload`` — the
    # template reads ``document.upload.content_type`` + ``size_bytes`` per row.
    query = (
        db.query(KnowledgeDocument)
        .options(selectinload(KnowledgeDocument.upload))
        .filter(
            KnowledgeDocument.user_id == current_user.id,
            KnowledgeDocument.deleted_at.is_(None),
        )
    )
    if category:
        query = query.filter(KnowledgeDocument.category == category)
    if status:
        query = query.filter(KnowledgeDocument.status == status)
    if source_kind:
        query = query.filter(KnowledgeDocument.source_kind == source_kind.value)
    documents = query.order_by(KnowledgeDocument.updated_at.desc()).all()
    return {
        "status": "success",
        "documents": [_document_payload(doc) for doc in documents],
    }


@router.get("/knowledge/documents/{document_id}")
def get_knowledge_document(
    document_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    document = (
        db.query(KnowledgeDocument)
        .filter(
            KnowledgeDocument.id == document_id,
            KnowledgeDocument.user_id == current_user.id,
            KnowledgeDocument.deleted_at.is_(None),
        )
        .first()
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Knowledge document not found")
    return {"status": "success", "document": _document_payload(document)}


@router.patch("/knowledge/documents/{document_id}")
def update_knowledge_document(
    document_id: str,
    request: KnowledgeDocumentUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    document = (
        db.query(KnowledgeDocument)
        .filter(
            KnowledgeDocument.id == document_id,
            KnowledgeDocument.user_id == current_user.id,
        )
        .first()
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Knowledge document not found")
    if request.title is not None:
        document.title = request.title.strip() or document.title
    if request.category is not None:
        document.category = request.category.strip() or "默认"
    db.add(document)
    db.commit()
    db.refresh(document)
    return {"status": "success", "document": _document_payload(document)}


@router.delete("/knowledge/documents/{document_id}")
def delete_knowledge_document(
    document_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    document = (
        db.query(KnowledgeDocument)
        .filter(
            KnowledgeDocument.id == document_id,
            KnowledgeDocument.user_id == current_user.id,
        )
        .first()
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Knowledge document not found")
    try:
        hard_delete_knowledge_document(db, document)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.error("Knowledge document deletion failed: %s", exc)
        raise HTTPException(status_code=500, detail=humanize_error(exc)) from exc
    # Postgres facts are gone now; external index/blob cleanup is durable in
    # the outbox and can finish asynchronously.
    return {"status": "success"}


@router.get("/knowledge/categories")
def list_knowledge_categories(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = (
        db.query(KnowledgeDocument.category, func.count(KnowledgeDocument.id))
        .filter(
            KnowledgeDocument.user_id == current_user.id,
            KnowledgeDocument.deleted_at.is_(None),
        )
        .group_by(KnowledgeDocument.category)
        .order_by(KnowledgeDocument.category.asc())
        .all()
    )
    return {
        "status": "success",
        "categories": [
            {"category": category, "count": count} for category, count in rows
        ],
    }
