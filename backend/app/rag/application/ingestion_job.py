"""Admission, preparation and fenced publication for a canonical source document.

Database transactions never span file download, parser or embedding work. The
admitted source snapshot is propagated through every stage and checked again
before terminal writes. A late worker cannot revive a deleted/replaced source.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from app.core.async_runtime import run_async
from app.core.error_messages import humanize_error
from app.models.knowledge import KnowledgeDocument
from app.rag.index.source import IndexSourceChanged, SourceSnapshot, source_snapshot

logger = logging.getLogger(__name__)
TRANSIENT_INGEST_ERRORS = (ConnectionError, TimeoutError, OSError)


@dataclass(frozen=True)
class _Input:
    source: SourceSnapshot
    purpose: str
    file_id: str
    filename: str
    content_type: str | None
    storage_uri: str
    object_key: str


def _current(db, document_id, expected):
    doc = (
        db.query(KnowledgeDocument)
        .filter(KnowledgeDocument.id == document_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if doc is None or source_snapshot(db, doc) != expected:
        raise IndexSourceChanged("source changed during ingestion")
    return doc


def execute_ingestion(
    document_id: str,
    *,
    task_id,
    retries: int,
    max_retries: int,
    session_factory,
    wake_attachment_turns,
):
    from app.core.runtime_files import create_runtime_temp_file
    from app.core.storage import download_file_from_s3
    from app.rag.cleaning import EmptyContentError
    from app.rag.embedding_registry import EmbeddingValidationError
    from app.rag.ingest.pipeline import ingest_document, ingest_transcript
    from app.rag.application.library.document_formats import (
        UnsupportedDocumentFormat,
        validate_knowledge_document_format,
    )
    from app.rag.application.library.knowledge_service import dump_json_list
    from app.usage.runtime import for_owner

    def finish(status, error=None, result=None):
        with session_factory() as db:
            doc = _current(db, document_id, prepared.source)
            doc.status, doc.error_message = status, error
            if result is not None:
                doc.chunk_count = int(result.get("chunk_count") or 0)
                doc.ref_doc_ids = dump_json_list(result.get("ref_doc_ids") or [])
                doc.content_text = result.get("content_text")
            db.commit()
            # Load scalar identity before closing; notification owns its transaction.
            _ = doc.id, doc.source_kind
            db.expunge(doc)
        return wake_attachment_turns(doc) if status in {"ready", "failed"} else []

    prepared = None
    path = None
    try:
        with session_factory() as db:
            doc = db.get(KnowledgeDocument, document_id)
            if doc is None:
                return {
                    "status": "failed",
                    "error": f"Knowledge document not found: {document_id}",
                }
            if doc.deleted_at is not None or doc.status not in {"processing", "failed"}:
                _ = doc.id, doc.source_kind, doc.status
                db.expunge(doc)
                return {
                    "status": "skipped",
                    "document_id": document_id,
                    "current_status": doc.status,
                    "resumed_turn_ids": wake_attachment_turns(doc),
                }
            if doc.task_id and task_id and doc.task_id != task_id:
                raise IndexSourceChanged("task superseded before ingestion")
            snapshot = source_snapshot(db, doc)
            asset = doc.upload
            if asset is None or asset.user_id != doc.user_id:
                raise ValueError("Knowledge upload owner does not match document owner")
            prepared = _Input(
                snapshot,
                asset.purpose,
                asset.id,
                asset.original_filename,
                asset.content_type,
                doc.storage_uri or "",
                doc.object_key or "",
            )
        # No Session or checked-out database connection during slow work.
        if prepared.purpose not in {"knowledge_document", "interview_audio"}:
            raise ValueError("Attachment upload has invalid purpose")
        if (
            prepared.purpose == "interview_audio"
            and snapshot.source_kind != "chat_attachment"
        ):
            raise ValueError("Audio transcription is only valid for chat attachments")
        if prepared.purpose == "knowledge_document":
            validate_knowledge_document_format(prepared.filename, prepared.content_type)
        if not prepared.storage_uri.startswith("s3://"):
            raise ValueError("Knowledge ingestion only accepts owned S3 uploads")
        prefix = f"uploads/{snapshot.user_id}/{prepared.file_id}/"
        from app.core.storage import parse_s3_uri

        _, storage_key = parse_s3_uri(prepared.storage_uri)
        if (
            not prepared.object_key.startswith(prefix)
            or storage_key != prepared.object_key
        ):
            raise ValueError("Knowledge upload object key does not match owner prefix")
        path = create_runtime_temp_file(suffix=os.path.splitext(prepared.object_key)[1])
        with for_owner(snapshot.user_id, operation=f"ingest:{document_id}:{task_id}"):
            download_file_from_s3(prepared.storage_uri, path)
            # Reject a concurrent edit before paying for ASR/parser/embedding.
            with session_factory() as db:
                _current(db, document_id, snapshot)
            common = dict(
                document_id=document_id,
                upload_id=prepared.file_id,
                expected_source=snapshot,
            )
            if prepared.purpose == "interview_audio":
                from app.media.application.audio_transcription_service import (
                    transcribe_media,
                )

                transcript = run_async(transcribe_media(path, language=None))
                result = run_async(
                    ingest_transcript(
                        transcript, snapshot.source_kind, snapshot.user_id, **common
                    )
                )
            else:
                result = run_async(
                    ingest_document(
                        path,
                        snapshot.source_kind,
                        snapshot.user_id,
                        index_document=snapshot.source_kind != "chat_attachment",
                        **common,
                    )
                )
        if not result or not result.get("success"):
            resumed = finish("failed", "Empty or unparseable document")
            return {
                "status": "failed",
                "error": "Empty or unparseable document",
                "resumed_turn_ids": resumed,
            }
        indexed = result.get("indexed", True)
        resumed = finish(
            "ready" if indexed else "processing",
            None if indexed else "向量索引暂时不可用，正在后台重试，稍后可用。",
            result,
        )
        response = {
            "status": "success" if indexed else "indexing_queued",
            "document_id": document_id,
        }
        if indexed:
            response["resumed_turn_ids"] = resumed
        return response
    except IndexSourceChanged:
        logger.info("Discarded superseded ingestion for document %s", document_id)
        return {"status": "superseded", "document_id": document_id}
    except (
        UnsupportedDocumentFormat,
        EmptyContentError,
        EmbeddingValidationError,
    ) as exc:
        try:
            resumed = finish("failed", str(exc)[:500]) if prepared else []
        except IndexSourceChanged:
            return {"status": "superseded", "document_id": document_id}
        return {
            "status": "failed",
            "error": str(exc),
            "document_id": document_id,
            "resumed_turn_ids": resumed,
        }
    except Exception as exc:
        will_retry = isinstance(exc, TRANSIENT_INGEST_ERRORS) and retries < (
            max_retries or 0
        )
        if prepared:
            try:
                finish(
                    "processing" if will_retry else "failed",
                    (
                        f"Attempt {retries + 1} will retry: {humanize_error(exc)}"
                        if will_retry
                        else f"导入失败：{humanize_error(exc)}"
                    )[:500],
                )
            except (IndexSourceChanged, PermissionError):
                return {"status": "superseded", "document_id": document_id}
            except Exception:
                logger.exception(
                    "Could not persist ingestion failure for %s", document_id
                )
        raise
    finally:
        if path and os.path.exists(path):
            os.unlink(path)
