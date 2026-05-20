import logging
from enum import Enum
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.core.security import get_current_user
from app.db.database import get_db
from app.models.knowledge import KnowledgeDocument
from app.models.user import User
from app.rag.retriever import query_knowledge_base
from app.services.knowledge_service import default_title, hard_delete_knowledge_document
from app.services.upload_service import create_owned_upload, get_owned_upload, mark_upload_consumed
from app.worker.tasks import process_document_ingestion

logger = logging.getLogger(__name__)

router = APIRouter(tags=["rag"])


class SourceTypeEnum(str, Enum):
    interview_qa = "interview_qa"
    official_docs = "official_docs"
    personal_memory = "personal_memory"


class KnowledgeUploadRequest(BaseModel):
    filename: str
    content_type: Optional[str] = "application/octet-stream"
    size_bytes: Optional[int] = None


class KnowledgeDocumentCreateRequest(BaseModel):
    upload_id: str
    source_type: SourceTypeEnum = SourceTypeEnum.interview_qa
    title: Optional[str] = None
    category: str = "默认"


class KnowledgeDocumentUpdateRequest(BaseModel):
    title: Optional[str] = None
    category: Optional[str] = None


class QueryRequest(BaseModel):
    query: str = Field(..., description="User question directed at the LLM")
    source_type: Optional[SourceTypeEnum] = Field(None, description="Optional metadata filter bounds")


@router.post("/rag/query")
async def api_query_knowledge_base(
    request: QueryRequest,
    current_user: User = Depends(get_current_user),
):
    """Execute a user-scoped RAG query against the configured vector store."""
    try:
        source_type_val = request.source_type.value if request.source_type else None

        result = await query_knowledge_base(
            request.query,
            source_type=source_type_val,
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
    # Pull file metadata off the related UserUpload row if it loaded with the
    # document (SQLAlchemy lazy-loads when accessed).
    upload = document.upload
    content_type = upload.content_type if upload else None
    size_bytes = upload.size_bytes if upload else None
    return {
        "id": document.id,
        "upload_id": document.upload_id,
        "title": document.title,
        "category": document.category,
        "source_type": document.source_type,
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
async def create_knowledge_upload_url(
    request: KnowledgeUploadRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create an owned knowledge upload and return a presigned upload URL."""
    upload, url_info = create_owned_upload(
        db,
        user_id=current_user.username,
        filename=request.filename,
        purpose="knowledge_document",
        content_type=request.content_type,
        size_bytes=request.size_bytes,
    )
    return {
        "status": "success",
        "upload_id": upload.id,
        "upload_url": url_info["upload_url"],
        "filename": upload.original_filename,
    }


@router.post("/knowledge/documents")
async def create_knowledge_document(
    request: KnowledgeDocumentCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        upload = get_owned_upload(
            db,
            upload_id=request.upload_id,
            user_id=current_user.username,
            purpose="knowledge_document",
        )
        if upload is None:
            raise HTTPException(status_code=404, detail="Upload not found")
        if upload.status not in {"pending_upload", "uploaded"}:
            raise HTTPException(status_code=409, detail="Upload has already been consumed")

        document = KnowledgeDocument(
            user_id=current_user.username,
            upload_id=upload.id,
            title=request.title or default_title(upload),
            category=request.category.strip() or "默认",
            source_type=request.source_type.value,
            storage_uri=upload.storage_uri,
            object_key=upload.object_key,
            status="processing",
        )
        db.add(document)
        mark_upload_consumed(db, upload)
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
    source_type: Optional[SourceTypeEnum] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # selectinload(.upload) avoids an N+1 in ``_document_payload`` — the
    # template reads ``document.upload.content_type`` + ``size_bytes`` per row.
    query = (
        db.query(KnowledgeDocument)
        .options(selectinload(KnowledgeDocument.upload))
        .filter(KnowledgeDocument.user_id == current_user.username)
    )
    if category:
        query = query.filter(KnowledgeDocument.category == category)
    if status:
        query = query.filter(KnowledgeDocument.status == status)
    if source_type:
        query = query.filter(KnowledgeDocument.source_type == source_type.value)
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
        .filter(KnowledgeDocument.id == document_id, KnowledgeDocument.user_id == current_user.username)
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
        .filter(KnowledgeDocument.id == document_id, KnowledgeDocument.user_id == current_user.username)
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
        .filter(KnowledgeDocument.id == document_id, KnowledgeDocument.user_id == current_user.username)
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
    invalidate_bm25_cache(current_user.username)
    return {"status": "success"}


@router.get("/knowledge/categories")
async def list_knowledge_categories(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = (
        db.query(KnowledgeDocument.category, func.count(KnowledgeDocument.id))
        .filter(KnowledgeDocument.user_id == current_user.username)
        .group_by(KnowledgeDocument.category)
        .order_by(KnowledgeDocument.category.asc())
        .all()
    )
    return {
        "status": "success",
        "categories": [{"category": category, "count": count} for category, count in rows],
    }
