"""Resume tool: read_resume.

Wraps ResumeService to read the user's parsed resume sections.
"""

import asyncio
from typing import Any

from pydantic import BaseModel, Field

from app.agent_runtime.tool_registry import AgentToolContext, ToolEntry, registry


class ReadResumeArgs(BaseModel):
    section_types: list[str] = Field(
        default=[],
        description="Filter by section type: 'summary', 'project', 'education', 'skill'. Empty = all sections.",
    )


async def _read_resume_handler(args: ReadResumeArgs, ctx: AgentToolContext) -> dict[str, Any]:
    """Async wrapper — entire body is sync DB + chunk reads, so
    offload to a worker thread to keep the agent loop responsive."""
    return await asyncio.to_thread(_read_resume_sync, args, ctx)


def _read_resume_sync(args: ReadResumeArgs, ctx: AgentToolContext) -> dict[str, Any]:
    """Read the user's default personal resume.

    Resumes are a first-class entity (``resumes``) — never knowledge documents.
    Read order:

      1. ``resume_sections`` (structured/parsed, keyed by ``resume_id``) — the
         preferred path; format + return.
      2. else the entity's ``raw_text_snapshot`` full text.
      3. else a "not parsed yet / no resume" hint — but NEVER claim "no resume"
         when one demonstrably exists.
    """
    from app.db.database import SessionLocal
    from app.services.resume import resume_entity_service
    from app.services.resume.resume_service import resume_service

    with SessionLocal() as db:
        resumes = resume_entity_service.list_resumes(db, user_id=ctx.user_id)
        if not resumes:
            return {
                "section_count": 0,
                "raw_resume_available": False,
                "error": (
                    "No resume found for this user. Suggest uploading one in "
                    "「个人信息 → 我的简历」。"
                ),
            }
        # Default resume is canonical; fall back to the first active one.
        primary = next((r for r in resumes if r.is_default), resumes[0])
        primary_id = primary.id
        primary_title = primary.title
        primary_is_default = bool(primary.is_default)
        primary_parse_status = primary.parse_status
        primary_raw = (primary.raw_text_snapshot or "").strip()

    sections = resume_service.get_sections_by_resume(primary_id)
    if sections:
        formatted = resume_service.format_for_context(
            sections,
            section_types=args.section_types if args.section_types else None,
        )
        section_summary = []
        for s in sections:
            if args.section_types and s.section_type not in args.section_types:
                continue
            section_summary.append({
                "type": s.section_type,
                "title": s.title,
                "content": s.content[:800],
            })
        return {
            "resume_id": primary_id,
            "title": primary_title,
            "is_default": primary_is_default,
            "section_count": len(section_summary),
            "sections": section_summary,
            "formatted_text": formatted[:8000],
        }

    # No parsed sections yet — fall back to the entity's raw text snapshot.
    if primary_raw:
        return {
            "resume_id": primary_id,
            "title": primary_title,
            "is_default": primary_is_default,
            "section_count": 0,
            "raw_resume_available": True,
            "source": "raw_text_snapshot",
            "parse_status": primary_parse_status,
            "full_text": primary_raw[:18000],
        }

    return {
        "resume_id": primary_id,
        "title": primary_title,
        "section_count": 0,
        "raw_resume_available": True,
        "source": "empty",
        "parse_status": primary_parse_status,
        "hint": (
            f"Resume '{primary_title}' exists but isn't parsed yet "
            f"(parse_status={primary_parse_status}). If 'pending', tell the user "
            f"to wait a few seconds and retry; if 'failed', re-upload."
        ),
    }


registry.register(ToolEntry(
    name="read_resume",
    description=(
        "Read the user's default personal resume. Tries the parsed "
        "``resume_sections`` first; falls back to the resume entity's "
        "``raw_text_snapshot``. Returns either structured sections or "
        "``full_text`` plus metadata. Resumes are a personal entity, "
        "never knowledge documents."
    ),
    args_model=ReadResumeArgs,
    handler=_read_resume_handler,
    # Bumped from 10K to 20K to accommodate the full-text fallback —
    # the handler caps full_text at 18K internally, leaving headroom
    # for the surrounding JSON envelope.
    max_result_chars=20000,
    emoji="📄",
))
