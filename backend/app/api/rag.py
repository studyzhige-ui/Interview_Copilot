import os
import logging
from enum import Enum
from pydantic import BaseModel, Field
from typing import Optional
from fastapi import APIRouter, HTTPException

from app.rag.ingestion import ingest_document
from app.rag.retriever import query_knowledge_base

logger = logging.getLogger(__name__)

router = APIRouter(tags=["rag"])

class SourceTypeEnum(str, Enum):
    interview_qa = "interview_qa"
    official_docs = "official_docs"
    personal_memory = "personal_memory"

class IngestRequest(BaseModel):
    file_path: str = Field(..., description="Local path to the document to be ingested")
    source_type: SourceTypeEnum = Field(..., description="Category metadata for RAG routing")

class QueryRequest(BaseModel):
    query: str = Field(..., description="User question directed at the LLM")
    source_type: Optional[SourceTypeEnum] = Field(None, description="Optional metadata filter bounds")

@router.post("/rag/query")
async def api_query_knowledge_base(request: QueryRequest):
    """
    Execute an isolation-capable RAG query using DeepSeek endpoints.
    """
    try:
        source_type_val = request.source_type.value if request.source_type else None
        
        result = await query_knowledge_base(request.query, source_type=source_type_val)
        
        return {
            "status": "success",
            "data": result
        }
    except Exception as e:
        logger.error(f"查询 API 底层引发错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/rag/ingest")
async def api_ingest_document(request: IngestRequest):
    """
    Ingest a document into the ChromaDB vector store.
    """
    try:
        # Pre-validate file existence
        if not os.path.exists(request.file_path):
            raise HTTPException(status_code=404, detail=f"File not found: {request.file_path}")
            
        success = await ingest_document(request.file_path, request.source_type.value)
        
        if success:
            return {
                "status": "success",
                "message": "Document ingested successfully into RAG.",
                "file_path": request.file_path,
                "source_type": request.source_type.value
            }
        else:
            raise HTTPException(status_code=400, detail="Document could not be parsed or was empty.")
            
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Ingestion API error: {e}")
        raise HTTPException(status_code=500, detail=f"Internal error during ingestion: {str(e)}")
