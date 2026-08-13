"""File I/O tools: read_file and write_file.

read_file  — Read a validated Conversation AttachmentRef or persisted output.
write_file — Export structured output (study plans, reports) as downloadable files.
"""

import asyncio
import io
import logging
from typing import Any

from pydantic import BaseModel, Field

from app.agent_runtime.tool_registry import AgentToolContext, ToolDefinition, registry
from app.agent_runtime.tool_policy import ToolEffect

logger = logging.getLogger(__name__)


# ── read_file ────────────────────────────────────────────────────────────

# Paging window for a single read_file call. The default reproduces the
# historical "first 20K chars" behavior; the cap bounds a single result so it
# never needs offloading (read_file is in _NEVER_PERSIST_TOOLS).
_DEFAULT_READ_LIMIT = 20_000
_MAX_READ_LIMIT = 50_000


class ReadFileArgs(BaseModel):
    attachment_ref_id: str = Field(
        default="",
        description=(
            "Validated AttachmentRef ID from the [Attachments] manifest. "
            "Use this for files attached to the current conversation."
        ),
    )
    source_ref_id: str = Field(
        default="",
        description=(
            "Validated InterviewSourceRef ID from a Debrief Project [Attachments] "
            "manifest. Use only inside that record's debrief conversation."
        ),
    )
    path: str = Field(
        default="",
        description="Path to a large persisted tool output (shown inside a <persisted-output> block) to read back. Takes precedence over attachment_ref_id.",
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="Character offset to start reading from. Pass the previous response's next_offset to page through a large file.",
    )
    limit: int = Field(
        default=_DEFAULT_READ_LIMIT,
        ge=1,
        description="Max characters to return per call (default 20000, capped at 50000).",
    )


async def _read_file_handler(
    args: ReadFileArgs, ctx: AgentToolContext
) -> dict[str, Any]:
    # The whole body does sync DB + sync S3 I/O — both block the event
    # loop. Offload to a thread so the agent loop stays responsive on
    # slow storage backends. SessionLocal isn't thread-safe across
    # ``await`` boundaries; opening + closing it entirely inside the
    # worker thread is fine.
    return await asyncio.to_thread(_read_file_sync, args, ctx)


def _read_file_sync(args: ReadFileArgs, ctx: AgentToolContext) -> dict[str, Any]:
    # Branch 1: read back a large persisted tool output (Stage A). Confined to
    # the current session's storage dir by resolve_persisted_path.
    if args.path:
        from app.agent_runtime.tool_result_storage import resolve_persisted_path

        target = resolve_persisted_path(ctx.session_id, args.path)
        if target is None:
            return {
                "error": "Persisted file not found or not accessible",
                "path": args.path,
            }
        content = target.read_text(encoding="utf-8", errors="replace")
        return _paginate(content, args, {"path": str(target)})

    # Branch 2: delegate the exact AttachmentRef to the shared Source Resolver.
    # There is deliberately no owner-wide upload/document fallback: Resume,
    # Artifact, and other product assets keep their own typed read tools.
    from app.rag.application.attachment_sources import (
        AttachmentParsingPendingError,
        AttachmentSourceUnavailableError,
        load_debrief_source_text,
        load_attachment_text,
    )

    try:
        if args.source_ref_id:
            loaded = load_debrief_source_text(
                user_id=ctx.user_id,
                session_id=ctx.session_id,
                source_ref_id=args.source_ref_id,
            )
        elif args.attachment_ref_id:
            loaded = load_attachment_text(
                user_id=ctx.user_id,
                session_id=ctx.session_id,
                attachment_ref_id=args.attachment_ref_id,
            )
        else:
            return {
                "error": (
                    "attachment_ref_id, source_ref_id, or persisted path is required"
                )
            }
        content = str(loaded.pop("content"))
        return _paginate(
            content,
            args,
            loaded,
        )
    except AttachmentParsingPendingError as exc:
        return {
            "error": "attachment_parsing_pending",
            "attachment_ref_ids": list(exc.attachment_ref_ids),
        }
    except AttachmentSourceUnavailableError as exc:
        return {
            "error": "attachment_unavailable",
            "attachment_ref_id": exc.attachment_ref_id,
            "reason": exc.reason,
            "status": exc.status,
        }


def _paginate(content: str, args: ReadFileArgs, base: dict[str, Any]) -> dict[str, Any]:
    """Return a windowed slice of *content* plus paging metadata.

    Default offset=0 / limit=20000 reproduces the historical "first 20K chars"
    result (now with paging fields); ``next_offset`` / ``has_more`` let the
    model read the remainder of a large file or persisted output on demand.
    """
    total = len(content)
    offset = max(args.offset, 0)
    limit = min(max(args.limit, 1), _MAX_READ_LIMIT)
    chunk = content[offset : offset + limit]
    next_offset = offset + len(chunk)
    has_more = next_offset < total
    return {
        **base,
        "content": chunk,
        "offset": offset,
        "returned_chars": len(chunk),
        "total_chars": total,
        "has_more": has_more,
        "next_offset": next_offset if has_more else None,
        "truncated": has_more,
    }


# ── write_file ───────────────────────────────────────────────────────────


class WriteFileArgs(BaseModel):
    filename: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Output filename (e.g. 'study_plan.md')",
    )
    content: str = Field(
        ..., min_length=1, description="File content to write (Markdown or plain text)"
    )


async def _write_file_handler(
    args: WriteFileArgs, ctx: AgentToolContext
) -> dict[str, Any]:
    # Sync DB + sync S3 upload — offload to thread so agent step isn't
    # blocked on storage latency.
    return await asyncio.to_thread(_write_file_sync, args, ctx)


def _write_file_sync(args: WriteFileArgs, ctx: AgentToolContext) -> dict[str, Any]:
    from app.db.database import SessionLocal
    from app.services.uploads.file_asset_service import create_file_asset

    db = SessionLocal()
    try:
        upload, url_info = create_file_asset(
            db,
            user_id=ctx.user_id,
            filename=args.filename,
            purpose="agent_output",
            content_type="text/markdown"
            if args.filename.endswith(".md")
            else "text/plain",
            size_bytes=len(args.content.encode("utf-8")),
        )

        from app.core.storage import upload_file_to_owned_key

        file_obj = io.BytesIO(args.content.encode("utf-8"))
        actual_uri = upload_file_to_owned_key(
            file_obj,
            upload.object_key,
            content_type=upload.content_type,
        )
        if actual_uri != upload.storage_uri:
            # S3 was down and the bytes fell back to local disk — record
            # where they actually live, or every later read_file fails
            # against a phantom s3:// URI (UP-8).
            upload.storage_uri = actual_uri

        from app.services.uploads.file_asset_service import mark_file_asset_consumed

        mark_file_asset_consumed(db, upload)
        db.commit()

        return {
            "upload_id": upload.id,
            "filename": args.filename,
            "size_bytes": len(args.content.encode("utf-8")),
            "message": f"File '{args.filename}' saved successfully.",
        }
    except Exception as exc:
        db.rollback()
        logger.error("write_file failed (%s)", type(exc).__name__)
        return {"error": "Failed to write file"}
    finally:
        db.close()


# ── Registration ─────────────────────────────────────────────────────────

# read_file: max_result_chars is set high intentionally — read_file output
# must NEVER be persisted by the tool_result_storage layer.  This prevents
# the persist→read→persist infinite loop.
# The tool_result_storage module also lists read_file in _NEVER_PERSIST_TOOLS
# as a second layer of protection.
registry.register(
    ToolDefinition(
        name="read_file",
        description=(
            "Read a conversation attachment or persisted tool output with paging. "
            "For an attached file, pass its validated attachment_ref_id from "
            "the [Attachments] manifest."
        ),
        args_model=ReadFileArgs,
        handler=_read_file_handler,
        effect=ToolEffect.READ,
        concurrency_safe=True,
        max_result_chars=200_000,
        emoji="📂",
    )
)

registry.register(
    ToolDefinition(
        name="write_file",
        description="Export structured output as a downloadable file. Use for study plans, analysis reports, preparation guides, learning notes, etc. Supports Markdown and plain text.",
        args_model=WriteFileArgs,
        handler=_write_file_handler,
        effect=ToolEffect.INTERNAL_WRITE,
        max_result_chars=2000,
        emoji="💾",
    )
)
