"""File I/O tools: read_file and write_file.

read_file  — Read user-uploaded files (resume, JD, notes) by upload_id or purpose.
write_file — Export structured output (study plans, reports) as downloadable files.
"""

import io
import logging
from typing import Any

from pydantic import BaseModel, Field

from app.agent_runtime.tool_registry import AgentToolContext, ToolEntry, registry

logger = logging.getLogger(__name__)


# ── read_file ────────────────────────────────────────────────────────────

class ReadFileArgs(BaseModel):
    upload_id: str = Field(default="", description="Specific upload ID to read. Leave empty to read the latest file of a given purpose.")
    purpose: str = Field(default="", description="File purpose filter: 'resume', 'jd', 'audio', or empty for any.")


async def _read_file_handler(args: ReadFileArgs, ctx: AgentToolContext) -> dict[str, Any]:
    from app.db.database import SessionLocal
    from app.models.upload import UserUpload

    db = SessionLocal()
    try:
        if args.upload_id:
            upload = (
                db.query(UserUpload)
                .filter(UserUpload.id == args.upload_id, UserUpload.user_id == ctx.user_id)
                .first()
            )
        elif args.purpose:
            upload = (
                db.query(UserUpload)
                .filter(UserUpload.user_id == ctx.user_id, UserUpload.purpose == args.purpose)
                .order_by(UserUpload.created_at.desc())
                .first()
            )
        else:
            upload = (
                db.query(UserUpload)
                .filter(UserUpload.user_id == ctx.user_id)
                .order_by(UserUpload.created_at.desc())
                .first()
            )

        if upload is None:
            return {"error": "No file found", "purpose": args.purpose, "upload_id": args.upload_id}

        # Read file content from storage
        content = _read_upload_content(upload)
        return {
            "upload_id": upload.id,
            "filename": upload.original_filename or "",
            "purpose": upload.purpose or "",
            "content": content[:20000],  # cap at 20K chars
            "truncated": len(content) > 20000,
        }
    finally:
        db.close()


def _read_upload_content(upload) -> str:
    """Read the text content of an uploaded file from storage."""
    storage_uri = upload.storage_uri or ""

    if storage_uri.startswith("s3://"):
        try:
            from app.services.storage_service import s3_client, parse_s3_uri
            bucket, key = parse_s3_uri(storage_uri)
            response = s3_client.get_object(Bucket=bucket, Key=key)
            raw = response["Body"].read()
            return raw.decode("utf-8", errors="replace")
        except Exception as exc:
            logger.warning("Failed to read from S3 %s: %s", storage_uri, exc)
            return f"[Error reading file: {exc}]"

    # Local file fallback
    try:
        from pathlib import Path
        path = Path(storage_uri)
        if path.exists():
            return path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        logger.warning("Failed to read local file %s: %s", storage_uri, exc)

    return "[File content unavailable]"


# ── write_file ───────────────────────────────────────────────────────────

class WriteFileArgs(BaseModel):
    filename: str = Field(..., min_length=1, max_length=200, description="Output filename (e.g. 'study_plan.md')")
    content: str = Field(..., min_length=1, description="File content to write (Markdown or plain text)")


async def _write_file_handler(args: WriteFileArgs, ctx: AgentToolContext) -> dict[str, Any]:
    from app.db.database import SessionLocal
    from app.services.upload_service import create_owned_upload

    db = SessionLocal()
    try:
        upload, url_info = create_owned_upload(
            db,
            user_id=ctx.user_id,
            filename=args.filename,
            purpose="agent_output",
            content_type="text/markdown" if args.filename.endswith(".md") else "text/plain",
            size_bytes=len(args.content.encode("utf-8")),
        )

        # Write content to storage
        from app.services.storage_service import upload_file_to_owned_key
        file_obj = io.BytesIO(args.content.encode("utf-8"))
        upload_file_to_owned_key(
            file_obj,
            upload.object_key,
            content_type=upload.content_type,
        )

        # Mark as consumed (uploaded)
        from app.services.upload_service import mark_upload_consumed
        mark_upload_consumed(db, upload)
        db.commit()

        return {
            "upload_id": upload.id,
            "filename": args.filename,
            "size_bytes": len(args.content.encode("utf-8")),
            "message": f"File '{args.filename}' saved successfully.",
        }
    except Exception as exc:
        db.rollback()
        logger.error("write_file failed: %s", exc)
        return {"error": f"Failed to write file: {exc}"}
    finally:
        db.close()


# ── Registration ─────────────────────────────────────────────────────────

# read_file: max_result_chars is set high intentionally — read_file output
# must NEVER be persisted by the tool_result_storage layer.  This prevents
# the persist→read→persist infinite loop.
# (Claude Code: FileReadTool.maxResultSizeChars = Infinity)
# The tool_result_storage module also has read_file in _NEVER_PERSIST_TOOLS
# as a second layer of protection.
registry.register(ToolEntry(
    name="read_file",
    description="Read content of a user-uploaded file (resume, JD, notes). Specify upload_id for a specific file, or purpose ('resume', 'jd') to read the latest file of that type.",
    args_model=ReadFileArgs,
    handler=_read_file_handler,
    max_result_chars=200_000,  # Never trigger persistence (Claude Code pattern)
    emoji="📂",
))

registry.register(ToolEntry(
    name="write_file",
    description="Export structured output as a downloadable file. Use for study plans, analysis reports, preparation guides, learning notes, etc. Supports Markdown and plain text.",
    args_model=WriteFileArgs,
    handler=_write_file_handler,
    max_result_chars=2000,
    emoji="💾",
))

