import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.core.rate_limit import RATE_EXPENSIVE, RATE_UPLOAD, limiter
from app.core.security import get_current_user
from app.core.user_identity import resolve_user_pk
from app.db.database import get_db
from app.models.knowledge import KnowledgeDocument
from app.models.user import User
from app.rag.retriever import query_knowledge_base
from app.schemas.rag import (
    KnowledgeDocumentCreateRequest,
    KnowledgeDocumentUpdateRequest,
    KnowledgeUploadRequest,
    QueryRequest,
    SourceKindEnum,
)
from app.services.knowledge.knowledge_service import default_title, hard_delete_knowledge_document
from app.services.uploads.file_asset_service import (
    create_file_asset,
    get_owned_file_asset,
    mark_file_asset_consumed,
)
from app.worker.tasks import process_document_ingestion

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
    """Execute a user-scoped RAG query against the configured vector store."""
    try:
        source_kind_val = body.source_kind.value if body.source_kind else None

        result = await query_knowledge_base(
            body.query,
            source_kind=source_kind_val,
            user_id=current_user.username,
        )

        return {
            "status": "success",
            "data": result,
        }
    except Exception as exc:  # noqa: BLE001
        logger.error("RAG query API failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _document_payload(document: KnowledgeDocument) -> dict:
    # Pull file metadata off the related FileAsset row if it loaded with the
    # document (SQLAlchemy lazy-loads when accessed).
    upload = document.upload
    content_type = upload.content_type if upload else None
    size_bytes = upload.size_bytes if upload else None
    return {
        "id": document.id,
        "upload_id": document.upload_id,
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
async def create_knowledge_upload_url(
    request: Request,
    response: Response,
    body: KnowledgeUploadRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create an owned knowledge upload and return a presigned upload URL."""
    upload, url_info = create_file_asset(
        db,
        user_id=current_user.username,
        filename=body.filename,
        purpose="knowledge_document",
        content_type=body.content_type,
        size_bytes=body.size_bytes,
    )
    return {
        "status": "success",
        "upload_id": upload.id,
        "upload_url": url_info["upload_url"],
        "filename": upload.original_filename,
    }


@router.post("/knowledge/documents")
@limiter.limit(RATE_UPLOAD)
async def create_knowledge_document(
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
        if upload.upload_status not in {"pending_upload", "uploaded"}:
            raise HTTPException(status_code=409, detail="Upload has already been consumed")

        document = KnowledgeDocument(
            user_id=resolve_user_pk(db, current_user.username),
            upload_id=upload.id,
            title=body.title or default_title(upload),
            category=body.category.strip() or "默认",
            source_kind=body.source_kind.value,
            storage_uri=upload.storage_uri,
            object_key=upload.object_key,
            status="processing",
        )
        db.add(document)
        mark_file_asset_consumed(db, upload)
        # Flush so document.id is assigned and the row is visible to the
        # Celery worker when it queries (commit happens below, BEFORE we
        # dispatch — otherwise the worker can race ahead of our commit and
        # see no row). We don't dispatch yet because Celery.delay() can fail
        # (Redis broker outage) and we want the option to mark the document
        # as failed in the same DB session.
        db.flush()
        document_id = document.id

        try:
            task = process_document_ingestion.delay(document_id)
        except Exception as exc:  # noqa: BLE001
            # Dispatch failed — record it on the document so the UI surfaces
            # a real error instead of a forever-processing row, then commit
            # everything in one transaction.
            logger.error("Celery dispatch failed for document %s: %s", document_id, exc)
            document.status = "failed"
            document.error_message = f"task dispatch failed: {exc}"[:500]
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
            detail=f"Internal error dispatching ingestion: {exc}",
        ) from exc


@router.get("/knowledge/documents")
async def list_knowledge_documents(
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
        .filter(KnowledgeDocument.user_id == resolve_user_pk(db, current_user.username))
    )
    if category:
        query = query.filter(KnowledgeDocument.category == category)
    if status:
        query = query.filter(KnowledgeDocument.status == status)
    if source_kind:
        query = query.filter(KnowledgeDocument.source_kind == source_kind.value)
    documents = query.order_by(KnowledgeDocument.updated_at.desc()).all()
    return {"status": "success", "documents": [_document_payload(doc) for doc in documents]}


@router.get("/knowledge/documents/{document_id}")
async def get_knowledge_document(
    document_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    document = (
        db.query(KnowledgeDocument)
        .filter(KnowledgeDocument.id == document_id, KnowledgeDocument.user_id == resolve_user_pk(db, current_user.username))
        .first()
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Knowledge document not found")
    return {"status": "success", "document": _document_payload(document)}


@router.patch("/knowledge/documents/{document_id}")
async def update_knowledge_document(
    document_id: str,
    request: KnowledgeDocumentUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    document = (
        db.query(KnowledgeDocument)
        .filter(KnowledgeDocument.id == document_id, KnowledgeDocument.user_id == resolve_user_pk(db, current_user.username))
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
async def delete_knowledge_document(
    document_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    document = (
        db.query(KnowledgeDocument)
        .filter(KnowledgeDocument.id == document_id, KnowledgeDocument.user_id == resolve_user_pk(db, current_user.username))
        .first()
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Knowledge document not found")
    try:
        hard_delete_knowledge_document(db, document)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.error("Knowledge document deletion failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to delete document: {exc}") from exc
    # Flush the BM25 cache so the next retrieval doesn't surface
    # snippets from the just-deleted document.
    from app.rag.bm25_cache import invalidate_bm25_cache
    invalidate_bm25_cache(resolve_user_pk(db, current_user.username))
    return {"status": "success"}


@router.get("/knowledge/categories")
async def list_knowledge_categories(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = (
        db.query(KnowledgeDocument.category, func.count(KnowledgeDocument.id))
        .filter(KnowledgeDocument.user_id == resolve_user_pk(db, current_user.username))
        .group_by(KnowledgeDocument.category)
        .order_by(KnowledgeDocument.category.asc())
        .all()
    )
    return {
        "status": "success",
        "categories": [{"category": category, "count": count} for category, count in rows],
    }
