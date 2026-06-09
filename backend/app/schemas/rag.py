"""Pydantic schemas for /rag + /knowledge HTTP endpoints.

Mirrors the request shapes used by ``app/api/rag.py``: presigned-URL
issuance for knowledge uploads, KnowledgeDocument CRUD, and the
``/rag/query`` LLM-grounding endpoint.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class SourceKindEnum(str, Enum):
    """KnowledgeDocument system source kind (RFC §5.1). ``personal_memory`` is
    NOT a knowledge-document kind — its write path was removed in MEMORY-V3
    (long-term user state lives in ``memory_ability_states`` now) and any
    preserved ``document_chunks`` were dropped in migration 0039. It is excluded
    from knowledge read paths and is intentionally not a member here.

    - ``user_upload``: a user-uploaded file (题库/官方文档/面经/笔记…).
    - ``improved_qa``: a QA improved-answer the user saved from an interview.
    - ``manual_text``: a directly pasted/hand-written doc (reserved).
    """
    user_upload = "user_upload"
    improved_qa = "improved_qa"
    manual_text = "manual_text"


class KnowledgeUploadRequest(BaseModel):
    """``POST /knowledge/upload`` — get a presigned URL for the raw blob."""
    filename: str
    content_type: Optional[str] = "application/octet-stream"
    size_bytes: Optional[int] = None


class KnowledgeDocumentCreateRequest(BaseModel):
    """``POST /knowledge/documents`` — register an uploaded blob as a doc."""
    upload_id: str  # the file_assets.id of the confirmed upload
    source_kind: SourceKindEnum = SourceKindEnum.user_upload
    title: Optional[str] = None
    category: str = "默认"


class KnowledgeDocumentUpdateRequest(BaseModel):
    """``PATCH /knowledge/documents/{doc_id}`` request body."""
    title: Optional[str] = None
    category: Optional[str] = None


class QueryRequest(BaseModel):
    """``POST /rag/query`` — user question grounded against the KB."""
    query: str = Field(..., description="User question directed at the LLM")
    source_kind: Optional[SourceKindEnum] = Field(None, description="Optional metadata filter bounds")


__all__ = [
    "SourceKindEnum",
    "KnowledgeUploadRequest",
    "KnowledgeDocumentCreateRequest",
    "KnowledgeDocumentUpdateRequest",
    "QueryRequest",
]
