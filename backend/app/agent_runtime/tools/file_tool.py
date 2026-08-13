"""Scoped source reads and Artifact-backed file exports.

read_file  — Read a validated source or canonical Tool result.
write_file — Save a versioned Artifact and materialize its downloadable file.
"""

import asyncio
import hashlib
import io
import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from app.agent_runtime.tool_registry import AgentToolContext, ToolDefinition, registry
from app.agent_runtime.tool_policy import ToolEffect

logger = logging.getLogger(__name__)


# ── read_file ────────────────────────────────────────────────────────────

# Paging window for a single read_file call. The default reproduces the
# historical "first 20K chars" behavior; the cap bounds a single result so it
# never needs another result-reference projection.
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
    tool_call_id: str = Field(
        default="",
        max_length=128,
        description=(
            "Exact Tool Call ID shown inside a <tool-result-reference> block. "
            "Reads the canonical redacted result from the current Turn and "
            "takes precedence over attachment_ref_id."
        ),
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
    # Branch 1: page the canonical redacted result owned by an exact Tool Call.
    # The same Turn/session/user fence prevents guessing another tenant's call
    # identity. There is deliberately no worker-local file fallback.
    if args.tool_call_id:
        return _read_canonical_tool_result(args, ctx)

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
                    "attachment_ref_id, source_ref_id, or tool_call_id is required"
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


def _read_canonical_tool_result(
    args: ReadFileArgs,
    ctx: AgentToolContext,
) -> dict[str, Any]:
    from app.core.user_identity import resolve_user_pk
    from app.db.database import SessionLocal
    from app.models.agent_execution import AgentToolCall

    if not ctx.turn_id:
        return {
            "error": "tool_result_scope_unavailable",
            "tool_call_id": args.tool_call_id,
        }

    db = SessionLocal()
    try:
        user_pk = ctx.user_pk or resolve_user_pk(db, ctx.user_id)
        if user_pk is None:
            return {
                "error": "tool_result_scope_unavailable",
                "tool_call_id": args.tool_call_id,
            }
        row = (
            db.query(AgentToolCall)
            .filter(
                AgentToolCall.call_id == args.tool_call_id,
                AgentToolCall.turn_id == ctx.turn_id,
                AgentToolCall.session_id == ctx.session_id,
                AgentToolCall.user_id == user_pk,
            )
            .one_or_none()
        )
        if (
            row is None
            or row.result_json is None
            or row.status in {"running", "waiting", "deferred"}
        ):
            return {
                "error": "tool_result_unavailable",
                "tool_call_id": args.tool_call_id,
            }
        content = json.dumps(
            row.result_json,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return _paginate(
            content,
            args,
            {
                "tool_call_id": row.call_id,
                "tool_name": row.tool_name,
                "result_status": row.status,
                "read_mode": "canonical_tool_result",
            },
        )
    finally:
        db.close()


def _paginate(content: str, args: ReadFileArgs, base: dict[str, Any]) -> dict[str, Any]:
    """Return a windowed slice of *content* plus paging metadata.

    Default offset=0 / limit=20000 reproduces the historical "first 20K chars"
    result (now with paging fields); ``next_offset`` / ``has_more`` let the
    model read the remainder of a large source or Tool result on demand.
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
        "coverage": {
            **(base.get("coverage") if isinstance(base.get("coverage"), dict) else {}),
            "segment_start": offset,
            "segment_end": next_offset,
            "total_chars": total,
            "starts_at_beginning": offset == 0,
            "reaches_end": not has_more,
            "single_call_full_coverage": offset == 0 and not has_more,
        },
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
    from app.core.user_identity import resolve_user_pk
    from app.db.database import SessionLocal
    from app.db.types import utc_now
    from app.models.artifact import Artifact, ArtifactVersion
    from app.models.file_asset import FileAsset
    from app.schemas.artifact import ArtifactProvenanceInput, ArtifactWriteInput
    from app.services import artifact_service
    from app.services.uploads.file_asset_service import (
        enqueue_asset_blob_delete,
        mark_file_asset_consumed,
        store_validated_file_asset,
    )

    db = SessionLocal()
    upload_id: str | None = None
    artifact_committed = False
    try:
        turn_id = (ctx.turn_id or "").strip()
        if not turn_id:
            return {"error": "artifact_source_turn_unavailable"}
        user_pk = ctx.user_pk or resolve_user_pk(db, ctx.user_id)
        if user_pk is None:
            return {"error": "artifact_owner_unavailable"}
        call_identity = (ctx.tool_call_id or "").strip() or (
            f"{args.filename}\0{args.content}"
        )
        digest = hashlib.sha256(
            f"{turn_id}\0{call_identity}".encode("utf-8")
        ).hexdigest()
        operation_key = f"write-file:{digest}"
        existing = (
            db.query(Artifact)
            .filter(
                Artifact.user_id == user_pk,
                Artifact.creation_key == operation_key,
            )
            .one_or_none()
        )
        if existing is not None:
            version = (
                db.query(ArtifactVersion)
                .filter(ArtifactVersion.artifact_id == existing.id)
                .order_by(ArtifactVersion.version_no.asc())
                .first()
            )
            if (
                version is None
                or version.title != args.filename
                or version.content_text != args.content
            ):
                return {"error": "artifact_export_identity_conflict"}
            return _write_file_result(existing, version)

        content_format = (
            "markdown" if args.filename.casefold().endswith(".md") else "plain_text"
        )
        upload = store_validated_file_asset(
            db,
            user_id=ctx.user_id,
            filename=args.filename,
            purpose="agent_output",
            file_obj=io.BytesIO(args.content.encode("utf-8")),
            content_type=(
                "text/markdown" if content_format == "markdown" else "text/plain"
            ),
            size_bytes=len(args.content.encode("utf-8")),
        )
        upload_id = upload.id
        mark_file_asset_consumed(db, upload)
        artifact = artifact_service.save_artifact_explicitly(
            db,
            user_pk=user_pk,
            operation_key=operation_key,
            artifact_kind="agent_export",
            version=ArtifactWriteInput(
                title=args.filename,
                content_text=args.content,
                content_format=content_format,
                file_asset_id=upload.id,
                provenance=ArtifactProvenanceInput(source_turn_id=turn_id),
            ),
        )
        db.commit()
        artifact_committed = True
        version = (
            db.query(ArtifactVersion)
            .filter(ArtifactVersion.artifact_id == artifact.id)
            .order_by(ArtifactVersion.version_no.desc())
            .first()
        )
        if version is None:  # defensive: the Application Service writes both
            raise RuntimeError("artifact version missing after save")
        return _write_file_result(artifact, version)
    except Exception as exc:
        db.rollback()
        if upload_id is not None and not artifact_committed:
            orphan = db.get(FileAsset, upload_id)
            if orphan is not None:
                orphan.upload_status = "delete_pending"
                orphan.deleted_at = utc_now()
                enqueue_asset_blob_delete(db, orphan)
                db.commit()
        logger.error("write_file failed (%s)", type(exc).__name__)
        return {"error": "Failed to write file"}
    finally:
        db.close()


def _write_file_result(artifact, version) -> dict[str, Any]:
    return {
        "artifact_id": artifact.id,
        "artifact_version_id": version.id,
        "version_no": version.version_no,
        "file_asset_id": version.file_asset_id,
        "filename": version.title,
        "external_action_performed": False,
        "message": "Artifact version and downloadable file saved.",
    }


# ── Registration ─────────────────────────────────────────────────────────

# read_file stays inline so a paged result can never recursively point at
# another Tool-result reference. The projection layer enforces this again.
registry.register(
    ToolDefinition(
        name="read_file",
        description=(
            "Read a scoped attachment or canonical Tool result with paging. "
            "For an attached file, pass its validated attachment_ref_id from "
            "the [Attachments] manifest. For an oversized Tool result, pass the "
            "exact tool_call_id from its <tool-result-reference> block."
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
        description=(
            "Explicitly save structured output as one versioned Artifact backed "
            "by a downloadable file. This proves the Artifact/version exists; "
            "it does not prove the file was submitted or sent externally."
        ),
        args_model=WriteFileArgs,
        handler=_write_file_handler,
        effect=ToolEffect.INTERNAL_WRITE,
        max_result_chars=2000,
        emoji="💾",
    )
)
