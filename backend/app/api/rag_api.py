import logging
from enum import Enum
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.security import get_current_user
from app.models.user import User
from app.rag.retriever import query_knowledge_base
from app.services.storage_service import generate_presigned_upload_url
from app.worker.tasks import process_document_ingestion

logger = logging.getLogger(__name__)

router = APIRouter(tags=["rag"])


class SourceTypeEnum(str, Enum):
    interview_qa = "interview_qa"
    official_docs = "official_docs"
    personal_memory = "personal_memory"


class IngestRequest(BaseModel):
    file_path: str = Field(..., description="S3 URI pointer to the cloud document (e.g. s3://...)")
    source_type: SourceTypeEnum = Field(..., description="Category metadata for RAG routing")


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


class RAGPresignedUrlRequest(BaseModel):
    filename: str


@router.post("/rag/upload/url")
async def get_rag_upload_presigned_url(
    request: RAGPresignedUrlRequest,
    current_user: User = Depends(get_current_user),
):
    """Generate a presigned URL for direct document upload."""
    url_info = generate_presigned_upload_url(request.filename)
    return {
        "status": "success",
        "upload_url": url_info["upload_url"],
        "file_path": url_info["file_path"],
    }


@router.post("/rag/ingest")
async def api_ingest_document(
    request: IngestRequest,
    current_user: User = Depends(get_current_user),
):
    """Dispatch a document ingestion job to the RAG backend workers."""
    try:
        task = process_document_ingestion.delay(
            file_path_or_url=request.file_path,
            source_type=request.source_type.value,
            user_id=current_user.username,
        )

        return {
            "status": "processing",
            "message": "Document ingestion dispatched successfully to the RAG backend workers.",
            "file_path": request.file_path,
            "source_type": request.source_type.value,
            "task_id": task.id,
        }

    except Exception as exc:  # noqa: BLE001
        logger.error("Ingestion API dispatch error: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Internal error dispatching ingestion: {exc}",
        ) from exc
