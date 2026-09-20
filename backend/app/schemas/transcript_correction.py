"""Source corrections are explicit commands against an immutable transcript ID."""

from __future__ import annotations

import uuid
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Role = Literal["candidate", "interviewer", "unknown"]


class TranscriptWordEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    word_id: str = Field(pattern=r"^w\d{6}$")
    text: str | None = Field(default=None, min_length=1, max_length=500)
    speaker_id: str | None = Field(default=None, min_length=1, max_length=80)

    @model_validator(mode="after")
    def change_present(self):
        if not self.model_fields_set.intersection({"text", "speaker_id"}):
            raise ValueError("word edit must contain text or speaker_id")
        if "text" in self.model_fields_set and (
            self.text is None or not self.text.strip()
        ):
            raise ValueError("source text cannot be erased or blank")
        return self


class TranscriptCorrectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request_id: str = Field(min_length=36, max_length=36)
    expected_transcript_id: str = Field(min_length=1, max_length=80)
    words: list[TranscriptWordEdit] = Field(default_factory=list, max_length=200)
    speaker_roles: dict[str, Role] = Field(default_factory=dict, max_length=32)
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("request_id")
    @classmethod
    def canonical_uuid(cls, value):
        if str(uuid.UUID(value)) != value:
            raise ValueError("request_id must be a canonical UUID")
        return value

    @model_validator(mode="after")
    def validate_command(self):
        if not self.reason.strip() or not (self.words or self.speaker_roles):
            raise ValueError("correction requires a reason and actual source edits")
        if len({x.word_id for x in self.words}) != len(self.words):
            raise ValueError("duplicate word correction")
        return self


class TranscriptCorrectionReceipt(BaseModel):
    request_id: str
    previous_transcript_id: str
    transcript_id: str
    current_transcript_id: str
    review_generation: int
    created_at: str
    reanalysis_required: bool = True


class TranscriptWordView(BaseModel):
    word_id: str
    text: str
    start: float | None
    end: float | None
    alignment_status: str
    speaker_id: str | None
    overlap: bool


class TranscriptPage(BaseModel):
    transcript_id: str
    current_transcript_id: str
    source: str
    language: str | None
    audio_file_asset_id: str
    duration_seconds: float
    word_count: int
    words: list[TranscriptWordView]
    speakers: list[str]
    confirmed_roles: dict[str, Role]
    suggested_roles: dict[str, Role]
    next_offset: int | None


class TranscriptHistoryItem(BaseModel):
    request_id: str
    previous_transcript_id: str
    transcript_id: str
    reason: str
    word_ids: list[str]
    confirmed_roles: dict[str, Role]
    created_at: str


class TranscriptHistoryPage(BaseModel):
    items: list[TranscriptHistoryItem]
    next_cursor: str | None
