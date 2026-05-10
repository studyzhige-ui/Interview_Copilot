import asyncio
import json
import logging
import threading

from app.db.database import SessionLocal
from app.models.interview import AnalysisResult, Interview, Transcript
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
    max_retries=3,
)
def process_interview_analysis(self, interview_id: int):
    """Transcribe an interview recording, analyze it, and persist the results."""
    from app.services.analysis_service import analyze_interview
    from app.services.transcription_service import transcribe_media

    db = SessionLocal()
    try:
        interview = db.query(Interview).filter(Interview.id == interview_id).first()
        if not interview:
            return {"error": f"Interview not found: {interview_id}"}

        interview.status = "TRANSCRIBING"
        db.commit()

        import os

        file_path_or_url = interview.file_url
        if not file_path_or_url:
            raise ValueError(f"Interview {interview_id} has no file_url")
        if interview.upload and interview.upload.user_id != interview.user_id:
            raise ValueError("Interview upload owner does not match interview owner")
        if interview.upload and not interview.upload.object_key.startswith(
            f"uploads/{interview.user_id}/{interview.upload_id}/"
        ):
            raise ValueError("Interview upload object key does not match owner prefix")

        local_file_path = file_path_or_url
        is_temp_file = False

        if file_path_or_url.startswith("s3://"):
            import tempfile

            from app.services.storage_service import download_file_from_s3

            logger.info("[Task %s] Downloading S3 object for transcription.", self.request.id)
            _, ext = os.path.splitext(file_path_or_url)
            tmp_fd, local_file_path = tempfile.mkstemp(suffix=ext)
            os.close(tmp_fd)

            download_file_from_s3(file_path_or_url, local_file_path)
            is_temp_file = True

        try:
            logger.info("[Task %s] Transcribing media: %s", self.request.id, local_file_path)
            transcript_text = run_async(transcribe_media(local_file_path))

            interview.status = "ANALYZING"
            db.commit()

            logger.info("[Task %s] Analyzing transcript.", self.request.id)
            analysis_data = run_async(analyze_interview(transcript_text))

            new_transcript = Transcript(
                interview_id=interview.id,
                content=transcript_text,
                raw_text=transcript_text,
            )
            db.add(new_transcript)

            new_analysis = AnalysisResult(
                interview_id=interview.id,
                score=analysis_data.get("overall_score", 0),
                feedback=analysis_data.get("overall_feedback", ""),
                improved_answer=json.dumps(analysis_data.get("qa_list", []), ensure_ascii=False),
            )
            db.add(new_analysis)

            # Create InterviewRecord for debrief chat sessions
            from app.services.interview_record_service import interview_record_service

            analysis_json_str = json.dumps(analysis_data, ensure_ascii=False)
            interview_record_service.create_from_upload(
                user_id=interview.user_id,
                title=f"面试录音 #{interview.id}",
                audio_upload_id=str(interview.upload_id) if interview.upload_id else None,
                transcript=transcript_text,
                analysis_json=analysis_json_str,
                db=db,
            )

            interview.status = "COMPLETED"
            db.commit()

            return {"status": "success", "interview_id": interview_id}
        finally:
            if is_temp_file and os.path.exists(local_file_path):
                os.unlink(local_file_path)
                logger.info("[Task %s] Removed temporary file: %s", self.request.id, local_file_path)

    except Exception as exc:
        db.rollback()
        interview = db.query(Interview).filter(Interview.id == interview_id).first()
        if interview:
            interview.status = "FAILED"
            db.commit()
        logger.error("Interview analysis task failed: %s", exc)
        raise
    finally:
        db.close()


@celery_app.task(
    bind=True,
    name="tasks.process_document_ingestion",
    autoretry_for=(ConnectionError, TimeoutError, OSError),
    retry_backoff=True,
    retry_backoff_max=120,
    max_retries=3,
)
def process_document_ingestion(self, document_id: str):
    """Download an uploaded document if needed and ingest it into Milvus/Docstore."""
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
