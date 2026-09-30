"""Source-linked preparation; lexical leads are not verified qualifications."""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.mock_preparation import MockPreparationRequest


class Excerpt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str


class PreparationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requirement: Excerpt
    evidence_candidates: list[Excerpt]
    shared_terms: list[str]
    status: Literal["review_evidence", "evidence_not_located"]
    practice_focus: str


class PreparationBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    method: Literal["source-excerpts-v1"] = "source-excerpts-v1"
    snapshot_id: str
    resume_version_id: str
    resume_sha256: str
    jd_sha256: str
    items: list[PreparationItem]
    resume_excerpts: list[Excerpt]
    omitted_resume_excerpt_count: int = Field(ge=0)
    start_request: MockPreparationRequest
    markdown: str
    disclaimer: str
