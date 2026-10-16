from typing import Literal
from uuid import uuid4
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

Stage = Literal[
    "saved", "applied", "screening", "interview", "in_process", "offer", "closed"
]


class Contact(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    role: str = Field(default="", max_length=200)
    email: str = Field(default="", max_length=300)
    phone: str = Field(default="", max_length=100)


class JobEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_version: int
    company_name: str = Field(min_length=1, max_length=200)
    job_title: str = Field(min_length=1, max_length=300)
    location: str = Field(default="", max_length=200)
    source_url: str = Field(default="", max_length=4000)
    notes: str = Field(default="", max_length=20000)
    contacts: list[Contact] = Field(default_factory=list, max_length=30)
    hidden: bool = False


class JobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    operation_key: str = Field(min_length=1, max_length=100)
    company_name: str = Field(min_length=1, max_length=200)
    job_title: str = Field(min_length=1, max_length=300)
    location: str = Field(default="", max_length=200)
    source_url: str = Field(default="", max_length=4000)
    description: str = Field(default="", max_length=120000)


class StageChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int
    operation_key: str = Field(min_length=1, max_length=100)
    stage: Stage
    outcome: (
        Literal["rejected", "withdrawn", "posting_closed", "declined_offer", "accepted"]
        | None
    ) = None
    occurred_at: AwareDatetime
    note: str = Field(default="", max_length=10000)
    channel: str | None = Field(default=None, max_length=160)
    # Exact saved versions, never a moving 'current resume' pointer.
    version_ids: list[str] = Field(default_factory=list, max_length=20)


class DocumentSection(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=100)
    content: str = Field(default="", max_length=30000)


class ResumeDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    name: str = Field(default="", max_length=200)
    headline: str = Field(default="", max_length=300)
    contact: str = Field(default="", max_length=2000)
    summary: str = Field(default="", max_length=10000)
    sections: list[DocumentSection] = Field(default_factory=list, max_length=30)
    template: Literal["classic", "modern"] = "classic"
    accent: Literal["forest", "slate", "blue"] = "forest"
    font_size: int = Field(default=11, ge=9, le=14)

    def plain_text(self):
        parts = [self.name, self.headline, self.contact, self.summary]
        parts.extend(f"## {s.title}\n{s.content}" for s in self.sections)
        return "\n\n".join(p for p in parts if p.strip()) or "待完善简历"

    def has_content(self):
        return any(
            p.strip() for p in (self.name, self.headline, self.contact, self.summary)
        ) or any(s.content.strip() for s in self.sections)

    @model_validator(mode="after")
    def unique_sections(self):
        if len({s.id for s in self.sections}) != len(self.sections):
            raise ValueError("章节标识不能重复")
        return self


class DocumentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    operation_key: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=240)
    kind: Literal["resume", "cover_letter", "portfolio"] = "resume"
    data: ResumeDocument
    opportunity_id: str | None = None


class DraftSave(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_revision: int = Field(ge=0)
    base_version_id: str
    title: str = Field(min_length=1, max_length=240)
    data: ResumeDocument
    operation_key: str = Field(
        default_factory=lambda: uuid4().hex, min_length=1, max_length=100
    )


class DocumentPublish(BaseModel):
    expected_revision: int
    operation_key: str = Field(min_length=1, max_length=100)
