"""Shared user/UI/Agent input contract; transport does not own mock semantics."""

from typing import Literal
from app.interviews.domain.specification import InterviewPurpose, InterviewSpecification
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class MockPreparationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    purpose: InterviewPurpose = "full"
    focus: str | None = Field(default=None, min_length=2, max_length=1000)
    resume_id: str | None = Field(default=None, min_length=1, max_length=128)
    jd_text: str | None = Field(
        default=None,
        min_length=20,
        max_length=50_000,
        description="Inline JD. Prefer an exact owned JD snapshot for long/reused descriptions.",
    )
    jd_snapshot_id: str | None = Field(default=None, min_length=1, max_length=36)
    jd_snapshot_version: int | None = Field(default=None, ge=1)
    job_opportunity_id: str | None = Field(default=None, min_length=1, max_length=35)
    input_mode: Literal["text", "voice"] = "text"
    interviewer_style: Literal["friendly", "professional", "rigorous", "pressure"] = (
        "professional"
    )
    target_question_count: Literal[15, 20, 30] = 20

    @field_validator(
        "resume_id", "jd_text", "jd_snapshot_id", "job_opportunity_id", mode="before"
    )
    @classmethod
    def strip_context(cls, value):
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_source(self):
        if (self.jd_snapshot_id is None) != (self.jd_snapshot_version is None):
            raise ValueError("JD snapshot id and version must be supplied together")
        spec = InterviewSpecification(purpose=self.purpose, focus=self.focus)
        if self.jd_text is not None and self.jd_snapshot_id is not None:
            raise ValueError("Supply at most one inline JD or exact JD snapshot")
        if spec.purpose == "full" and (
            self.jd_text is None and self.jd_snapshot_id is None
        ):
            raise ValueError("完整模拟面试需要 JD")
        if spec.purpose != "focused_practice" and self.resume_id is None:
            raise ValueError("完整模拟面试和项目深挖需要简历")
        self.focus = spec.focus
        if self.jd_snapshot_id is not None and self.job_opportunity_id is None:
            raise ValueError("A JD snapshot must name its owning job opportunity")
        return self
