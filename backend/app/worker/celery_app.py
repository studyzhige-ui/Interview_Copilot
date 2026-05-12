from celery import Celery
from celery.signals import worker_process_init

from app.core.config import settings

celery_app = Celery(
    "interview_copilot_worker",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.worker.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # Allow up to one hour for long transcription jobs.
)


@worker_process_init.connect
def init_worker_models(**kwargs):
    """Warm model resources when each Celery worker process starts."""
    import logging

    logger = logging.getLogger(__name__)
    logger.info(">>> Celery worker started; warming LLM, RAG, and audio models...")

    from app.rag.embeddings import init_rag_settings
    from app.services.voice.audio_transcription_service import init_whisper_model

    init_rag_settings()
    init_whisper_model()
    logger.info(">>> Celery model warmup complete.")
