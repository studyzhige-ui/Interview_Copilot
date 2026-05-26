"""Pydantic schemas for interview / upload / debrief HTTP endpoints.

Mirrors the request / response shapes used by ``app/api/interview.py``
(audio upload, analysis, memory-save, InterviewRecord CRUD, QA edits).
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class PresignedUrlRequest(BaseModel):
    """``POST /upload/audio/presigned`` request body."""
    filename: str
    content_type: Optional[str] = None
    size_bytes: Optional[int] = None


class AnalyzeRequest(BaseModel):
    """``POST /interview/analyze`` request body."""
    upload_id: str
    resume_upload_id: str
    jd_text: Optional[str] = None
    jd_upload_id: Optional[str] = None  # KnowledgeDocument id; if set, text is loaded server-side
    # ISO-639-1 language hint for WhisperX. ``"zh"`` / ``"en"`` force the
    # decoder, ``"auto"`` lets Whisper detect per-clip (slower, occasionally
    # picks the wrong one — only worth it for genuinely mixed audio).
    # Default matches the UI default of Simplified Chinese transcription.
    language: str = "zh"


class MemorySaveRequest(BaseModel):
    """``POST /memory/save`` — persist an improved-answer card to long-term memory."""
    question: str
    improved_answer: str
    original_score: float
    tags: Optional[List[str]] = Field(default_factory=list)


class InterviewRecordListItem(BaseModel):
    """Row shape for ``GET /interview-records``."""
    id: str
    source: str
    title: str
    tag: Optional[str] = None
    status: str
    created_at: str


class InterviewRecordUpdateRequest(BaseModel):
    """``PATCH /interview-records/{record_id}`` request body."""
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    tag: Optional[str] = Field(default=None, max_length=32)


class QAEditRequest(BaseModel):
    """``PATCH /interview-records/{record_id}/qa/{qa_id}`` request body."""
    question: Optional[str] = None
    answer: Optional[str] = None
    critique: Optional[str] = None
    improved_answer: Optional[str] = None


__all__ = [
    "PresignedUrlRequest",
    "AnalyzeRequest",
    "MemorySaveRequest",
    "InterviewRecordListItem",
    "InterviewRecordUpdateRequest",
    "QAEditRequest",
]
