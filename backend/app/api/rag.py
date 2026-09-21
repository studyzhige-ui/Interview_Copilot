from app.api.command_errors import command_errors
from app.rag.application import document_commands
import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.api.file_assets import upload_too_large_http
from app.core.edition import current_edition_policy
from app.core.error_messages import humanize_error
from app.core.rate_limit import RATE_EXPENSIVE, RATE_UPLOAD, limiter
from app.core.security import get_current_user
from app.db.database import get_db
from app.models.knowledge import KnowledgeDocument
from app.models.user import User
from app.rag.application.service import rag_service
from app.rag.domain.models import SearchIntent
from app.rag.runtime import ensure_rag_runtime
from app.schemas.rag import (
    KnowledgeDocumentCreateRequest,
    KnowledgeDocumentUpdateRequest,
    KnowledgeUploadRequest,
    QueryRequest,
    SourceKindEnum,
)
from app.rag.application.library.knowledge_service import hard_delete_knowledge_document
from app.files.application.file_asset_service import UploadTooLarge
from app.files.application.file_asset_service import create_file_asset
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

        result = await rag_service.retrieve(
            intents=[SearchIntent.from_query(body.query)],
            source_kind=source_kind_val,
            user_id=current_user.username,
        )

        return {
            "status": "success",
            "data": {
                "chunks": result.chunks,
                "retrieval_state": result.state.to_dict(),
                "diagnostics": result.diagnostics,
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
        "conversation_id": document.conversation_id,
        "status": document.status,
        "task_id": document.task_id,
        "chunk_count": document.chunk_count,
        "index_fingerprint": document.index_fingerprint,
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
    with command_errors():
        document, task_id = document_commands.create_document(
            db,
            current_user=current_user,
            body=body,
            dispatch=dispatch_document_ingestion,
        )
    return {
        "status": document.status,
        "document": _document_payload(document),
        "task_id": task_id,
    }


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
    else:
        query = query.filter(KnowledgeDocument.source_kind != "chat_attachment")
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
            KnowledgeDocument.source_kind != "chat_attachment",
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
    with command_errors():
        document = document_commands.update_document(
            db, document_id=document_id, request=request, current_user=current_user
        )
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
            KnowledgeDocument.source_kind != "chat_attachment",
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
            KnowledgeDocument.source_kind != "chat_attachment",
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
