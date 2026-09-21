"""A frozen purpose is separate from the text/voice transport and persona."""

from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

InterviewPurpose = Literal["full", "project_deep_dive", "focused_practice"]


class InterviewSpecification(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal["interview-spec-v1"] = "interview-spec-v1"
    purpose: InterviewPurpose = "full"
    focus: str | None = Field(default=None, min_length=2, max_length=1000)

    @field_validator("focus", mode="before")
    @classmethod
    def strip_focus(cls, value):
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def require_focus(self):
        if self.purpose != "full" and not self.focus:
            raise ValueError("专项练习或项目深挖必须说明本次考察目标")
        return self

    @property
    def stage_keys(self) -> tuple[str, ...]:
        if self.purpose == "project_deep_dive":
            return ("resume_project_deep_dive",)
        if self.purpose == "focused_practice":
            return ("role_technical_assessment",)
        return (
            "self_intro",
            "resume_project_deep_dive",
            "role_technical_assessment",
            "candidate_questions",
        )

    @property
    def title(self) -> str:
        return {
            "full": "完整模拟面试",
            "project_deep_dive": "项目深挖",
            "focused_practice": "专项练习",
        }[self.purpose]


def resolve_specification(
    value: dict | InterviewSpecification | None = None,
) -> InterviewSpecification:
    if isinstance(value, InterviewSpecification):
        return value
    # Historical records without a spec used exactly the four-stage full flow.
    return InterviewSpecification.model_validate(value or {})
