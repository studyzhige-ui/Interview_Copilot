"""Read the user's canonical resume Artifact."""

import asyncio
import hashlib
import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.schemas.mock_preparation import MockPreparationRequest

from app.agent_runtime.tool_registry import AgentToolContext, ToolDefinition, registry
from app.agent_runtime.tool_policy import ToolEffect

logger = logging.getLogger(__name__)


class ReadResumeArgs(BaseModel):
    """The default resume is selected by the canonical resume aggregate."""

    model_config = ConfigDict(extra="forbid")
    resume_id: str | None = Field(default=None, min_length=1, max_length=128)
    artifact_version_id: str | None = Field(default=None, min_length=1, max_length=128)
    text_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    offset: int = Field(default=0, ge=0, le=1_000_000)
    limit: int = Field(default=18_000, ge=1, le=18_000)

    @model_validator(mode="after")
    def pin_following_pages(self):
        if self.offset and (
            self.artifact_version_id is None
            or self.resume_id is None
            or self.text_sha256 is None
        ):
            raise ValueError("Resume pagination requires the exact resume and version")
        return self


async def _read_resume_handler(
    args: ReadResumeArgs, ctx: AgentToolContext
) -> dict[str, Any]:
    """Keep synchronous database access off the Agent event loop."""
    return await asyncio.to_thread(_read_resume_sync, ctx, args)


def _read_resume_sync(
    ctx: AgentToolContext, args: ReadResumeArgs | None = None
) -> dict[str, Any]:
    """Read the user's default canonical resume and exact current version."""
    try:
        return _read_resume_inner(ctx, args)
    except Exception as exc:
        logger.warning("read_resume failed (%s)", type(exc).__name__)
        return {"error": "Failed to read resume", "section_count": 0}


def _read_resume_inner(
    ctx: AgentToolContext, args: ReadResumeArgs | None = None
) -> dict[str, Any]:
    from app.core.user_identity import resolve_user_pk
    from app.db.database import SessionLocal
    from app.career.application.resumes import resume_artifact_service

    args = args or ReadResumeArgs()
    with SessionLocal() as db:
        user_pk = resolve_user_pk(db, ctx.user_id)
        resumes = (
            resume_artifact_service.list_resume_artifacts(db, user_pk=user_pk)
            if user_pk is not None
            else []
        )
        if not resumes:
            return {
                "error": "resume_artifact_not_found",
                "section_count": 0,
                "raw_resume_available": False,
                "message": (
                    "No canonical resume Artifact was found for this user. "
                    "Suggest uploading or importing one. Pre-cut-over Resume "
                    "rows must be materialized by migration 0029 before use."
                ),
            }
        primary = (
            resume_artifact_service.resolve_owned_resume(
                db, user_pk=user_pk, resume_id=args.resume_id
            )
            if args.resume_id
            else resumes[0]
        )
        if (
            args.artifact_version_id is not None
            and args.artifact_version_id != primary.current_version.id
        ):
            return {"error": "resume_version_changed", "raw_resume_available": False}

        try:
            text = resume_artifact_service.read_resume_text(primary)
        except resume_artifact_service.ResumeArtifactNotReadyError as exc:
            return {
                "error": "resume_artifact_not_ready",
                "resume_id": primary.artifact.id,
                "artifact_version_id": primary.current_version.id,
                "title": primary.current_version.title,
                "is_default": bool(primary.state.is_default),
                "section_count": 0,
                "raw_resume_available": False,
                "source": "artifact_version",
                "parse_status": primary.state.parse_status,
                "pending_profile_draft_id": primary.pending_draft_id,
                "message": str(exc),
            }
        text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if args.text_sha256 is not None and args.text_sha256 != text_hash:
            return {"error": "resume_content_changed", "raw_resume_available": False}
        if args.offset > len(text):
            return {"error": "resume_page_out_of_range", "raw_resume_available": False}
        end = min(len(text), args.offset + args.limit)
        return {
            "resume_id": primary.artifact.id,
            "artifact_version_id": primary.current_version.id,
            "title": primary.current_version.title,
            "is_default": bool(primary.state.is_default),
            "section_count": 0,
            "raw_resume_available": True,
            "source": "artifact_version",
            "parse_status": primary.state.parse_status,
            "pending_profile_draft_id": primary.pending_draft_id,
            "full_text": text[args.offset : end],
            "text_sha256": text_hash,
            "text_offset": args.offset,
            "text_total_characters": len(text),
            "text_complete": args.offset == 0 and end == len(text),
            "next_offset": end if end < len(text) else None,
        }


registry.register(
    ToolDefinition(
        name="read_resume",
        description=(
            "Read the user's default saved resume Artifact and its exact current "
            "version. Returns a bounded text page with explicit coverage and next_offset; "
            "later pages must pin resume_id, artifact_version_id and text_sha256. Legacy "
            "Resume identities work only when migration 0029 mapped them to the "
            "canonical Artifact aggregate."
        ),
        args_model=ReadResumeArgs,
        handler=_read_resume_handler,
        effect=ToolEffect.READ,
        concurrency_safe=True,
        # The handler caps full_text at 18K, leaving headroom for the envelope.
        max_result_chars=20000,
        emoji="📄",
    )
)


async def _preparation_handler(args: MockPreparationRequest, ctx: AgentToolContext):
    from app.interviews.application.preparation import build_preparation
    from app.db.database import SessionLocal

    if ctx.user_pk is None:
        raise ValueError("preparation_user_scope_unavailable")

    def read():
        with SessionLocal() as db:
            result = build_preparation(db, user_pk=ctx.user_pk, command=args)
            return result.model_dump(mode="json", exclude={"markdown"})

    return await asyncio.to_thread(read)


registry.register(
    ToolDefinition(
        name="prepare_interview_evidence",
        description="Read exact saved resume/JD excerpts, source-version fences and focused-practice leads. "
        "Lexical leads require user review; they are not confirmed qualifications or missing skills. "
        "This read never starts an interview, calls a model or overwrites profile/resume facts.",
        args_model=MockPreparationRequest,
        handler=_preparation_handler,
        effect=ToolEffect.READ,
        concurrency_safe=True,
        max_argument_chars=60_000,
        max_result_chars=500_000,
        emoji="📋",
    )
)
