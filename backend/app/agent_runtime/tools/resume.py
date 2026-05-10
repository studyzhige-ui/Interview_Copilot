"""Resume tool: read_resume.

Wraps ResumeService to read the user's parsed resume sections.
"""

from typing import Any

from pydantic import BaseModel, Field

from app.agent_runtime.tool_registry import AgentToolContext, ToolEntry, registry


class ReadResumeArgs(BaseModel):
    section_types: list[str] = Field(
        default=[],
        description="Filter by section type: 'summary', 'project', 'education', 'skill'. Empty = all sections.",
    )


async def _read_resume_handler(args: ReadResumeArgs, ctx: AgentToolContext) -> dict[str, Any]:
    from app.services.resume_service import resume_service

    sections = resume_service.get_sections_by_user(ctx.user_id)
    if not sections:
        return {"error": "No resume found for this user. Please upload a resume first."}

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
        "section_count": len(section_summary),
        "sections": section_summary,
        "formatted_text": formatted[:8000],
    }


registry.register(ToolEntry(
    name="read_resume",
    description="Read the user's uploaded resume. Returns structured sections (summary, project experience, education, skills). Use to understand user's background before giving advice.",
    args_model=ReadResumeArgs,
    handler=_read_resume_handler,
    max_result_chars=10000,
    emoji="📄",
))
