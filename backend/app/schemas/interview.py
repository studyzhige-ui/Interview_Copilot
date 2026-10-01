"""Pydantic schemas for interview / upload / debrief HTTP endpoints.

Mirrors the request / response shapes used by ``app/api/interviews/records.py``
(audio upload, analysis, InterviewRecord CRUD, QA edits).
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AnalyzeRequest(BaseModel):
    """``POST /interview/analyze`` request body.

    Resume context is optional and comes from EITHER a canonical resume
    Artifact (``resume_id``; migration aliases are accepted) or an ad-hoc file
    uploaded just for this interview (``resume_file_asset_id``, a
    file_assets.id). JD is a snapshot only —
    direct ``jd_text`` or a ``jd_file_asset_id`` (file_assets.id, purpose='jd');
    JD never becomes a knowledge document.
    """

    upload_id: str
    resume_id: Optional[str] = None
    resume_file_asset_id: Optional[str] = None
    jd_text: Optional[str] = None
    jd_file_asset_id: Optional[str] = None
    job_opportunity_id: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=35,
    )
    # ISO-639-1 language hint for WhisperX. ``"zh"`` / ``"en"`` force the
    # decoder, ``"auto"`` lets Whisper detect per-clip (slower, occasionally
    # picks the wrong one — only worth it for genuinely mixed audio).
    # Default matches the UI default of Simplified Chinese transcription.
    language: str = "zh"


class InterviewRecordListItem(BaseModel):
    """Row shape for ``GET /interview-records``."""

    id: str
    source: str
    title: str
    tag: Optional[str] = None
    job_opportunity_id: Optional[str] = None
    status: str
    created_at: str


class InterviewRecordUpdateRequest(BaseModel):
    """``PATCH /interview-records/{record_id}`` request body."""

    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    tag: Optional[str] = Field(default=None, max_length=32)
    # Omitted keeps the current association; explicit null clears it.
    job_opportunity_id: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=35,
    )


class QAEditRequest(BaseModel):
    """``PATCH /interview-records/{record_id}/qa/{qa_id}`` request body."""

    model_config = ConfigDict(extra="forbid", strict=True)
    expected_version: int = Field(ge=1)
    question: Optional[str] = Field(default=None, min_length=1, max_length=50_000)
    answer: Optional[str] = Field(default=None, max_length=100_000)
    critique: Optional[str] = Field(default=None, max_length=50_000)
    improved_answer: Optional[str] = Field(default=None, max_length=100_000)

    @model_validator(mode="after")
    def has_change(self):
        if all(
            getattr(self, field) is None
            for field in ("question", "answer", "critique", "improved_answer")
        ):
            raise ValueError("at least one edited field is required")
        if self.question is not None and not self.question.strip():
            raise ValueError("question must not be blank")
        return self


class SaveQARequest(BaseModel):
    """``POST /interview-records/{record_id}/qa/{qa_id}/save-to-knowledge``.

    Publishes the QA's improved answer as a knowledge_documents(improved_qa).
    """

    category: Optional[str] = Field(default=None, max_length=80)


__all__ = [
    "AnalyzeRequest",
    "InterviewRecordListItem",
    "InterviewRecordUpdateRequest",
    "QAEditRequest",
    "SaveQARequest",
]


class QATextSnapshot(BaseModel):
    question: str | None
    answer: str | None
    critique: str | None
    improved_answer: str | None


class QACorrectionView(BaseModel):
    id: str
    qa_id: str
    previous_version: int
    new_version: int
    before: QATextSnapshot
    after: QATextSnapshot
    created_at: str


class QACorrectionPage(BaseModel):
    items: list[QACorrectionView]
    next_cursor: str | None
