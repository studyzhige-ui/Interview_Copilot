"""Knowledge-document ingestion on the pipeline queue."""

import logging

from app.core.async_runtime import run_async
from app.core.error_messages import humanize_error
from app.db.database import SessionLocal
from app.models.knowledge import KnowledgeDocument
from app.task_queue.celery_app import celery_app

logger = logging.getLogger(__name__)

# Keep the business-state decision aligned with Celery's retry policy below.
# Any exception outside this tuple is terminal for this dispatch: Celery will
# not schedule another attempt, so the document must not remain "processing".
_TRANSIENT_INGEST_ERRORS = (ConnectionError, TimeoutError, OSError)


@celery_app.task(
    bind=True,
    name="tasks.process_document_ingestion",
    autoretry_for=_TRANSIENT_INGEST_ERRORS,
    retry_backoff=True,
    retry_backoff_max=120,
    retry_jitter=True,
    max_retries=3,
    acks_late=True,
    time_limit=1200,  # 20 min hard
    soft_time_limit=1140,
)
def process_document_ingestion(self, document_id: str):
    """Download an uploaded document if needed and ingest it into Milvus.

    Idempotency contract:
      * status='ready' (already ingested) → skip.
      * status='processing'/'failed' → fresh attempt. Re-ingest is safe:
        ``_index_nodes`` replaces this document's prior chunks (write_chunks
        deletes by document_id) and Milvus rows (delete-by-document_id before
        insert), so a retry never accumulates duplicate chunks.
    """
    import os

    from app.core.runtime_files import create_runtime_temp_file
    from app.core.storage import download_file_from_s3
    from app.rag.cleaning import EmptyContentError
    from app.rag.embedding_registry import EmbeddingValidationError
    from app.rag.ingestion import ingest_document
    from app.services.knowledge.document_formats import (
        UnsupportedDocumentFormat,
        validate_knowledge_document_format,
    )
    from app.services.knowledge.knowledge_service import dump_json_list

    db = SessionLocal()
    document = None
    local_file_path = None
    is_temp_file = False

    try:
        document = (
            db.query(KnowledgeDocument)
            .filter(KnowledgeDocument.id == document_id)
            .first()
        )
        if document is None:
            return {
                "status": "failed",
                "error": f"Knowledge document not found: {document_id}",
            }
        # document.user_id is the stable users.id (CLEANUP #2), as is the
        # FileAsset's — compare directly + use it for the pk-namespaced
        # object_key prefix below. The Milvus / document_chunks index now keys on
        # the stable users.id (CLEANUP #2) — which is exactly document.user_id —
        # so the pk goes straight to the ingest call (no pk->username bridge).
        owner_pk = document.user_id
        if not document.upload or document.upload.user_id != owner_pk:
            raise ValueError("Knowledge upload owner does not match document owner")
        if document.upload.purpose != "knowledge_document":
            raise ValueError("Knowledge document upload has invalid purpose")
        if document.status not in {"processing", "failed"}:
            return {
                "status": "skipped",
                "document_id": document_id,
                "current_status": document.status,
            }

        # Defensive format re-check (ingestion §4.1.2) — the API already
        # gated this, but a stale dispatch or a direct DB insert must not
        # reach the parser with an unsupported format. Raises
        # UnsupportedDocumentFormat (a permanent error) handled below.
        validate_knowledge_document_format(
            document.upload.original_filename,
            document.upload.content_type,
        )

        if not document.storage_uri.startswith("s3://"):
            raise ValueError("Knowledge ingestion only accepts owned S3 uploads")

        expected_prefix = f"uploads/{owner_pk}/{document.file_asset_id}/"
        if not document.object_key.startswith(expected_prefix):
            raise ValueError("Knowledge upload object key does not match owner prefix")

        logger.info(
            "[Task %s] Downloading S3 document for RAG ingestion.", self.request.id
        )
        _, ext = os.path.splitext(document.object_key)
        local_file_path = create_runtime_temp_file(suffix=ext)

        try:
            download_file_from_s3(document.storage_uri, local_file_path)
            is_temp_file = True
            logger.info(
                "[Task %s] Document downloaded to %s", self.request.id, local_file_path
            )
        except Exception:
            if os.path.exists(local_file_path):
                os.unlink(local_file_path)
            raise

        logger.info("[Task %s] Starting RAG ingestion into Milvus.", self.request.id)
        result = run_async(
            ingest_document(
                local_file_path,
                document.source_kind,
                owner_pk,
                document_id=document.id,
                upload_id=document.file_asset_id,
            )
        )

        if result and result.get("success"):
            document.chunk_count = int(result.get("chunk_count") or 0)
            document.ref_doc_ids = dump_json_list(result.get("ref_doc_ids") or [])
            document.content_text = result.get("content_text")
            if result.get("indexed", True):
                document.status = "ready"
                document.error_message = None
                db.add(document)
                db.commit()
                logger.info("[Task %s] Document ingestion completed.", self.request.id)
                return {"status": "success", "document_id": document_id}
            # Facts are saved but the Milvus write was queued for outbox retry
            # (Milvus was down). Stay 'processing' until the index lands — the
            # milvus_upsert_document handler flips this to ready (or to failed if
            # its retries exhaust), so the doc never stalls (plan §4.6.3 / C2).
            document.status = "processing"
            document.error_message = "向量索引暂时不可用，正在后台重试，稍后可用。"
            db.add(document)
            db.commit()
            logger.warning(
                "[Task %s] Facts saved; Milvus write queued for retry.", self.request.id
            )
            return {"status": "indexing_queued", "document_id": document_id}

        document.status = "failed"
        document.error_message = "Empty or unparseable document"
        db.add(document)
        db.commit()
        logger.warning("[Task %s] Document was empty or unparseable.", self.request.id)
        return {"status": "failed", "error": "Empty or unparseable document"}

    except (
        UnsupportedDocumentFormat,
        EmptyContentError,
        EmbeddingValidationError,
    ) as exc:
        # Permanent content/format/embedding error (unsupported format, S0
        # cleaning left no usable text, or a dimension/count mismatch that no
        # retry can fix) — friendly Chinese message, NO retry. document is
        # guaranteed bound here (raised after the None check above).
        document.status = "failed"
        document.error_message = str(exc)[:500]
        db.add(document)
        db.commit()
        logger.warning("[Task %s] Permanent ingest rejection: %s", self.request.id, exc)
        return {"status": "failed", "error": str(exc), "document_id": document_id}

    except Exception as exc:
        # Distinguish mid-retry vs final-attempt the same way
        # process_interview_analysis does. Mid-retry: a transient
        # status='failed' would make the UI flash "failed" between
        # retries; tag it as "retrying" instead so the user sees a
        # consistent in-progress signal until we give up for good.
        retries_left = max(0, (self.max_retries or 0) - self.request.retries)
        will_retry = isinstance(exc, _TRANSIENT_INGEST_ERRORS) and retries_left > 0
        if document is not None:
            try:
                if not will_retry:
                    document.status = "failed"
                    # Humanize the terminal user-facing message (e.g. a 402
                    # balance error during embedding); raw detail is logged.
                    document.error_message = f"导入失败：{humanize_error(exc)}"[:500]
                else:
                    # Don't mark as terminal "failed" mid-retry — leave
                    # status='processing' (the prior set_status from line
                    # 144's gate) and surface the latest error message
                    # for debug visibility.
                    document.error_message = (
                        f"Attempt {self.request.retries + 1} crashed; will retry. "
                        f"{type(exc).__name__}: {exc}"
                    )[:500]
                db.add(document)
                db.commit()
            except Exception as recovery_exc:  # noqa: BLE001
                logger.error(
                    "Failed to update document %s status after task crash: %s",
                    document.id,
                    recovery_exc,
                )
        logger.error(
            "[Task %s] RAG ingestion task failed (attempt %d/%d): %s",
            self.request.id,
            self.request.retries + 1,
            self.max_retries + 1,
            exc,
        )
        raise

    finally:
        if is_temp_file and os.path.exists(local_file_path):
            os.unlink(local_file_path)
            logger.info(
                "[Task %s] Removed temporary document: %s",
                self.request.id,
                local_file_path,
            )
        db.close()
