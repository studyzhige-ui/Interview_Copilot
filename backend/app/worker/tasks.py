import asyncio
import logging
import threading

from app.db.database import SessionLocal
from app.models.knowledge import KnowledgeDocument
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Reusable event loop for Celery workers
# ---------------------------------------------------------------------------
# Each Celery worker thread gets its own persistent event loop, avoiding the
# overhead of creating/destroying a loop on every task invocation.

_loop_local = threading.local()


def _get_worker_loop() -> asyncio.AbstractEventLoop:
    """Return a persistent event loop for the current worker thread."""
    loop = getattr(_loop_local, "loop", None)
    if loop is None or loop.is_closed():
        loop = asyncio.new_event_loop()
        _loop_local.loop = loop
    return loop


def run_async(coro):
    """Run an async coroutine inside a synchronous Celery task."""
    loop = _get_worker_loop()
    return loop.run_until_complete(coro)


@celery_app.task(
    bind=True,
    name="tasks.process_interview_analysis",
    autoretry_for=(ConnectionError, TimeoutError, OSError),
    retry_backoff=True,
    retry_backoff_max=120,
    retry_jitter=True,          # avoid thundering herd on transient outages
    max_retries=3,
    # Reliability: acks_late + time bounds. Keep both ceilings well below
    # the broker visibility_timeout (3700s) so a hung task is reclaimed and
    # re-delivered before Redis would re-deliver on its own.
    acks_late=True,
    time_limit=1800,            # 30 min hard
    soft_time_limit=1740,       # 1 min before hard kill
)
def process_interview_analysis(self, record_id: str, language: str = "zh"):
    """Run the unified analysis pipeline for an InterviewRecord.

    The orchestrator handles both source='upload' (audio → ASR → analysis)
    and source='mock' (composed transcript from QA buffer → analysis).

    ``language`` is a WhisperX language hint:
      * ``"zh"`` / ``"en"``: force the decoder to that language. Faster
        + much more accurate than auto-detect on clean monolingual audio.
      * ``"auto"``: let Whisper detect per clip. Use only for genuinely
        mixed-language recordings.
    Default ``"zh"`` matches the API's default and the UI default.

    Idempotent under retry: if the record is already in a terminal state
    (``completed``/``failed`` from a prior attempt that succeeded but whose
    ack we lost), short-circuit instead of re-running the entire pipeline.
    """
    from app.models.interview_record import InterviewRecord
    from app.services.interview.analysis_orchestrator import analysis_orchestrator
    from app.services.interview_record_service import interview_record_service

    # ── Idempotency gate ────────────────────────────────────────────────
    db = SessionLocal()
    try:
        row = db.query(InterviewRecord).filter(InterviewRecord.id == record_id).first()
        if row is not None and row.status == "completed":
            logger.info(
                "[Task %s] InterviewRecord %s already completed; skipping re-run.",
                self.request.id, record_id,
            )
            return {"status": "skipped", "record_id": record_id, "reason": "already_completed"}
    finally:
        db.close()

    # Stash the celery task id so the cancel endpoint can revoke us.
    try:
        interview_record_service.set_status(
            record_id,
            "pending",
            celery_task_id=self.request.id,
        )
    except Exception:  # noqa: BLE001
        logger.warning("Failed to stash celery_task_id on %s", record_id)

    try:
        return analysis_orchestrator.run(record_id, language=language)
    except Exception as exc:  # noqa: BLE001
        logger.error("Interview analysis task failed for %s: %s", record_id, exc)
        raise


@celery_app.task(
    bind=True,
    name="tasks.process_document_ingestion",
    autoretry_for=(ConnectionError, TimeoutError, OSError),
    retry_backoff=True,
    retry_backoff_max=120,
    retry_jitter=True,
    max_retries=3,
    acks_late=True,
    time_limit=1200,            # 20 min hard
    soft_time_limit=1140,
)
def process_document_ingestion(self, document_id: str):
    """Download an uploaded document if needed and ingest it into Milvus/Docstore.

    Idempotency contract:
      * status='ready' with chunks already written → skip
      * status='processing'/'failed' → fresh attempt; existing Milvus rows
        for ``ref_doc_ids`` (if any) are best-effort deleted first to avoid
        duplicate chunks on retry. Failure to delete is non-fatal.
    """
    import json
    import os
    import tempfile

    from app.rag.ingestion import ingest_document
    from app.services.knowledge_service import dump_json_list
    from app.services.storage_service import download_file_from_s3

    db = SessionLocal()
    document = None
    local_file_path = None
    is_temp_file = False

    try:
        document = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == document_id).first()
        if document is None:
            return {"status": "failed", "error": f"Knowledge document not found: {document_id}"}
        if not document.upload or document.upload.user_id != document.user_id:
            raise ValueError("Knowledge upload owner does not match document owner")
        if document.upload.purpose != "knowledge_document":
            raise ValueError("Knowledge document upload has invalid purpose")
        if document.status not in {"processing", "failed"}:
            return {"status": "skipped", "document_id": document_id, "current_status": document.status}

        # If this is a retry of a partially-succeeded attempt (we crashed
        # between Milvus insert and DB commit), log it. A Phase-3 follow-up
        # will delete stale Milvus rows for ``document.ref_doc_ids`` to avoid
        # duplicate chunks; for now status-gate is the main reliability win
        # and duplicates are filtered at query time by document_id.
        if self.request.retries > 0 and document.ref_doc_ids:
            stale_count = 0
            try:
                stale_count = len(json.loads(document.ref_doc_ids) or [])
            except json.JSONDecodeError:
                pass
            logger.warning(
                "[Task %s] Retry attempt #%d for document %s; %d stale ref_doc_ids "
                "from prior attempt may produce duplicates (filtered at query time).",
                self.request.id, self.request.retries, document_id, stale_count,
            )

        if not document.storage_uri.startswith("s3://"):
            raise ValueError("Knowledge ingestion only accepts owned S3 uploads")

        expected_prefix = f"uploads/{document.user_id}/{document.upload_id}/"
        if not document.object_key.startswith(expected_prefix):
            raise ValueError("Knowledge upload object key does not match owner prefix")

        logger.info("[Task %s] Downloading S3 document for RAG ingestion.", self.request.id)
        _, ext = os.path.splitext(document.object_key)
        tmp_fd, local_file_path = tempfile.mkstemp(suffix=ext)
        os.close(tmp_fd)

        try:
            download_file_from_s3(document.storage_uri, local_file_path)
            is_temp_file = True
            logger.info("[Task %s] Document downloaded to %s", self.request.id, local_file_path)
        except Exception:
            if os.path.exists(local_file_path):
                os.unlink(local_file_path)
            raise

        logger.info("[Task %s] Starting RAG ingestion into Milvus/Docstore.", self.request.id)
        result = run_async(
            ingest_document(
                local_file_path,
                document.source_type,
                document.user_id,
                document_id=document.id,
                upload_id=document.upload_id,
                category=document.category,
            )
        )

        if result and result.get("success"):
            document.status = "ready"
            document.chunk_count = int(result.get("chunk_count") or 0)
            document.node_ids = dump_json_list(result.get("node_ids") or [])
            document.ref_doc_ids = dump_json_list(result.get("ref_doc_ids") or [])
            document.error_message = None
            db.add(document)
            db.commit()
            logger.info("[Task %s] Document ingestion completed.", self.request.id)
            return {"status": "success", "document_id": document_id}

        document.status = "failed"
        document.error_message = "Empty or unparseable document"
        db.add(document)
        db.commit()
        logger.warning("[Task %s] Document was empty or unparseable.", self.request.id)
        return {"status": "failed", "error": "Empty or unparseable document"}

    except Exception as exc:
        if document is not None:
            document.status = "failed"
            document.error_message = str(exc)
            db.add(document)
            db.commit()
        logger.error("[Task %s] RAG ingestion task failed: %s", self.request.id, exc)
        raise

    finally:
        if is_temp_file and os.path.exists(local_file_path):
            os.unlink(local_file_path)
            logger.info("[Task %s] Removed temporary document: %s", self.request.id, local_file_path)
        db.close()
