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
    """Read the user's resume, with a graceful fallback for the common
    case where the upload landed in ``knowledge_documents`` but never
    got parsed into ``resume_sections``.

    Pre-fix screenshot: user had ``北京邮电大学-孙根武.pdf`` uploaded
    and marked ``ready`` in the Library, but this tool reported "No
    resume found" because it only consulted the parsed-sections table.
    That's a privacy-of-data-flow bug: the file IS there, the LLM was
    told it wasn't. New behaviour:

      1. Try ``resume_sections`` (the structured/parsed version) —
         this is the preferred path; format + return as before.
      2. If empty, check ``knowledge_documents`` for ``category=简历``
         rows. If any exist, return a helpful "raw upload exists,
         not yet parsed" payload so the LLM can either (a) call
         ``search_knowledge`` with relevant queries to read the body,
         or (b) tell the user to wait for parsing / re-upload — but
         NEVER claim "no resume" when one demonstrably exists.
      3. If neither table has anything, only THEN return the
         no-resume hint.
    """
    from app.services.resume_service import resume_service

    sections = resume_service.get_sections_by_user(ctx.user_id)
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
            "section_count": len(section_summary),
            "sections": section_summary,
            "formatted_text": formatted[:8000],
        }

    # No parsed sections — fall back to the raw upload table.
    from app.db.database import SessionLocal
    from app.models.knowledge import KnowledgeDocument

    db = SessionLocal()
    try:
        raw_resumes = (
            db.query(KnowledgeDocument)
            .filter(
                KnowledgeDocument.user_id == ctx.user_id,
                KnowledgeDocument.category == "简历",
            )
            .order_by(KnowledgeDocument.updated_at.desc())
            .all()
        )
    finally:
        db.close()

    if raw_resumes:
        # The raw PDF/DOCX is in the knowledge corpus but hasn't been
        # split into typed sections. Tell the LLM exactly that so it
        # can call search_knowledge for the body (the chunks live in
        # the LlamaIndex docstore reachable via the RAG retriever).
        return {
            "section_count": 0,
            "raw_resume_available": True,
            "raw_uploads": [
                {
                    "title": r.title,
                    "doc_id": r.id,
                    "status": r.status,
                    "uploaded_at": (r.created_at.isoformat() if r.created_at else None),
                }
                for r in raw_resumes
            ],
            "hint": (
                "The user has uploaded a resume (raw file in the knowledge "
                "corpus) but it has not been parsed into structured "
                "sections. To read its content use ``search_knowledge`` "
                "with queries like '工作经历', '教育背景', '技能', "
                "'项目经验' — the RAG retriever will pull the relevant "
                "chunks from the PDF. Do NOT tell the user 'no resume "
                "found' — they have one."
            ),
            "sections": [],
            "formatted_text": "",
        }

    # Genuinely no resume anywhere.
    return {
        "section_count": 0,
        "raw_resume_available": False,
        "error": (
            "No resume found for this user. Suggest uploading one to "
            "「资料库 → 文件 → 上传文件」 with category '简历'."
        ),
    }


registry.register(ToolEntry(
    name="read_resume",
    description="Read the user's uploaded resume. Returns structured sections (summary, project experience, education, skills). Use to understand user's background before giving advice.",
    args_model=ReadResumeArgs,
    handler=_read_resume_handler,
    max_result_chars=10000,
    emoji="📄",
))
