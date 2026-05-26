"""Pydantic schemas for /rag + /knowledge HTTP endpoints.

Mirrors the request shapes used by ``app/api/rag.py``: presigned-URL
issuance for knowledge uploads, KnowledgeDocument CRUD, and the
``/rag/query`` LLM-grounding endpoint.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class SourceTypeEnum(str, Enum):
    """Tag attached to a KnowledgeDocument; restricts /rag/query metadata
    filtering. Stored as a plain string column on the document row."""
    interview_qa = "interview_qa"
    official_docs = "official_docs"
    personal_memory = "personal_memory"


class KnowledgeUploadRequest(BaseModel):
    """``POST /knowledge/upload`` — get a presigned URL for the raw blob."""
    filename: str
    content_type: Optional[str] = "application/octet-stream"
    size_bytes: Optional[int] = None


class KnowledgeDocumentCreateRequest(BaseModel):
    """``POST /knowledge/documents`` — register an uploaded blob as a doc."""
    upload_id: str
    source_type: SourceTypeEnum = SourceTypeEnum.interview_qa
    title: Optional[str] = None
    category: str = "默认"


class KnowledgeDocumentUpdateRequest(BaseModel):
    """``PATCH /knowledge/documents/{doc_id}`` request body."""
    title: Optional[str] = None
    category: Optional[str] = None


class QueryRequest(BaseModel):
    """``POST /rag/query`` — user question grounded against the KB."""
    query: str = Field(..., description="User question directed at the LLM")
    source_type: Optional[SourceTypeEnum] = Field(None, description="Optional metadata filter bounds")


__all__ = [
    "SourceTypeEnum",
    "KnowledgeUploadRequest",
    "KnowledgeDocumentCreateRequest",
    "KnowledgeDocumentUpdateRequest",
    "QueryRequest",
]
