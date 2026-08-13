"""Read the user's canonical resume Artifact."""

import asyncio
import logging
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.agent_runtime.tool_registry import AgentToolContext, ToolDefinition, registry
from app.agent_runtime.tool_policy import ToolEffect

logger = logging.getLogger(__name__)


class ReadResumeArgs(BaseModel):
    """The default resume is selected by the canonical resume aggregate."""

    model_config = ConfigDict(extra="forbid")


async def _read_resume_handler(
    args: ReadResumeArgs, ctx: AgentToolContext
) -> dict[str, Any]:
    """Keep synchronous database access off the Agent event loop."""
    del args
    return await asyncio.to_thread(_read_resume_sync, ctx)


def _read_resume_sync(ctx: AgentToolContext) -> dict[str, Any]:
    """Read the user's default canonical resume and exact current version."""
    try:
        return _read_resume_inner(ctx)
    except Exception as exc:
        logger.warning("read_resume failed (%s)", type(exc).__name__)
        return {"error": "Failed to read resume", "section_count": 0}


def _read_resume_inner(ctx: AgentToolContext) -> dict[str, Any]:
    from app.core.user_identity import resolve_user_pk
    from app.db.database import SessionLocal
    from app.services.resume import resume_artifact_service

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
        primary = resumes[0]
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
            "full_text": text[:18000],
        }


registry.register(
    ToolDefinition(
        name="read_resume",
        description=(
            "Read the user's default saved resume Artifact and its exact current "
            "version. Returns full text plus parse/candidate metadata. Legacy "
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
