import asyncio
import json
import logging

from app.db.database import SessionLocal
from app.models.interview import AnalysisResult, Interview, Transcript
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


def run_async(coro):
    """Run an async coroutine inside a synchronous Celery task."""
    return asyncio.run(coro)


@celery_app.task(bind=True, name="tasks.process_interview_analysis")
def process_interview_analysis(self, interview_id: int, file_path_or_url: str):
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


@celery_app.task(bind=True, name="tasks.process_document_ingestion")
def process_document_ingestion(self, file_path_or_url: str, source_type: str, user_id: str):
    """Download an uploaded document if needed and ingest it into Milvus/Docstore."""
    import os
    import tempfile

    from app.rag.ingestion import ingest_document
    from app.services.storage_service import download_file_from_s3

    local_file_path = file_path_or_url
    is_temp_file = False

    if file_path_or_url.startswith("s3://"):
        logger.info("[Task %s] Downloading S3 document for RAG ingestion.", self.request.id)
        _, ext = os.path.splitext(file_path_or_url)
        tmp_fd, local_file_path = tempfile.mkstemp(suffix=ext)
        os.close(tmp_fd)

        try:
            download_file_from_s3(file_path_or_url, local_file_path)
            is_temp_file = True
            logger.info("[Task %s] Document downloaded to %s", self.request.id, local_file_path)
        except Exception:
            if os.path.exists(local_file_path):
                os.unlink(local_file_path)
            raise

    try:
        logger.info("[Task %s] Starting RAG ingestion into Milvus/Docstore.", self.request.id)
        success = run_async(ingest_document(local_file_path, source_type, user_id))

        if success:
            logger.info("[Task %s] Document ingestion completed.", self.request.id)
            return {"status": "success", "file_url": file_path_or_url}

        logger.warning("[Task %s] Document was empty or unparseable.", self.request.id)
        return {"status": "failed", "error": "Empty or unparseable document"}

    except Exception as exc:
        logger.error("[Task %s] RAG ingestion task failed: %s", self.request.id, exc)
        raise

    finally:
        if is_temp_file and os.path.exists(local_file_path):
            os.unlink(local_file_path)
            logger.info("[Task %s] Removed temporary document: %s", self.request.id, local_file_path)
