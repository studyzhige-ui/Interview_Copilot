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
        # The raw PDF/DOCX lives in the knowledge corpus and was parsed
        # into chunks (TextNodes) at upload time — the same parser the
        # RAG retriever uses. We read those chunks DIRECTLY from the
        # PostgresDocumentStore and concatenate them, so the LLM sees
        # the full resume text in one shot. Previously the fallback
        # told the LLM to call ``search_knowledge`` which returns
        # ~5 reranked chunks × 1500 chars (carved up + filtered) —
        # fragmented and misses sections. Direct docstore read is
        # exactly the right primitive for "give me the user's resume".
        from app.services.knowledge_service import json_list

        # Most-recent resume is the canonical one (the user may have
        # iterated). Tag the rest as "additional resumes available".
        primary = raw_resumes[0]
        primary_node_ids = json_list(primary.node_ids)

        full_text = ""
        nodes_read = 0
        if primary_node_ids:
            try:
                from llama_index.storage.docstore.postgres import (
                    PostgresDocumentStore,
                )
                from app.core.config import settings
                docstore = PostgresDocumentStore.from_uri(uri=settings.DATABASE_URL)
                pieces: list[str] = []
                for nid in primary_node_ids:
                    try:
                        node = docstore.get_document(nid)
                    except Exception:
                        continue
                    if node is None:
                        continue
                    text = getattr(node, "text", None) or getattr(node, "get_content", lambda: "")()
                    if text:
                        pieces.append(str(text))
                        nodes_read += 1
                # Concatenate chunks in the order they were stored —
                # this is the parser's left-to-right order for a PDF,
                # so headings stay above body paragraphs.
                full_text = "\n\n".join(pieces)
            except Exception as exc:  # noqa: BLE001
                # Docstore unreachable / module not importable — fall
                # through to a friendly hint instead of crashing the
                # whole agent turn. The agent can still pivot via
                # search_knowledge as a last resort.
                full_text = ""
                docstore_error = str(exc)
            else:
                docstore_error = ""
        else:
            docstore_error = ""

        if full_text:
            return {
                "section_count": 0,
                "raw_resume_available": True,
                "source": "docstore_direct",
                "title": primary.title,
                "doc_id": primary.id,
                "status": primary.status,
                "uploaded_at": (
                    primary.created_at.isoformat() if primary.created_at else None
                ),
                "node_count": nodes_read,
                # Truncate at 18K so we stay under the tool's
                # max_result_chars limit (raised to 20K below) with
                # headroom for the rest of the payload's JSON
                # overhead. Typical Chinese resumes run 2-6K chars,
                # so this rarely truncates anything.
                "full_text": full_text[:18000],
                "additional_resumes": [
                    {"title": r.title, "doc_id": r.id, "uploaded_at": (
                        r.created_at.isoformat() if r.created_at else None
                    )}
                    for r in raw_resumes[1:]
                ],
            }

        # Doc row exists but no readable chunks — likely still
        # processing (status=processing/pending) or ingestion failed.
        return {
            "section_count": 0,
            "raw_resume_available": True,
            "source": "docstore_empty",
            "title": primary.title,
            "doc_id": primary.id,
            "status": primary.status,
            "uploaded_at": (
                primary.created_at.isoformat() if primary.created_at else None
            ),
            "hint": (
                f"Resume '{primary.title}' is in the corpus but its "
                f"parsed nodes aren't yet available "
                f"(status={primary.status}). If status is 'processing' "
                f"or 'pending', ingestion is still running — tell the "
                f"user to wait ~30 seconds and retry. If status is "
                f"'failed', ingestion crashed — the user should re-upload."
                + (f" Docstore error: {docstore_error}" if docstore_error else "")
            ),
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
    description=(
        "Read the user's uploaded resume. Tries the parsed-sections "
        "table first; falls back to reading the raw PDF directly from "
        "the document store (concatenates all parsed chunks). Returns "
        "either structured sections or ``full_text`` plus metadata."
    ),
    args_model=ReadResumeArgs,
    handler=_read_resume_handler,
    # Bumped from 10K to 20K to accommodate the full-text fallback —
    # the handler caps full_text at 18K internally, leaving headroom
    # for the surrounding JSON envelope.
    max_result_chars=20000,
    emoji="📄",
))
