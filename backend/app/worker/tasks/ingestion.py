"""Knowledge-document ingestion on the pipeline queue."""

import logging

from app.db.database import SessionLocal
from app.models.knowledge import KnowledgeDocument
from app.task_queue.celery_app import celery_app
from app.conversation.application.turn_executor import attachment_resume_actions

from app.rag.application.ingestion_job import (
    TRANSIENT_INGEST_ERRORS,
    execute_ingestion,
)


logger = logging.getLogger(__name__)


def _wake_attachment_turns(document: KnowledgeDocument) -> list[str]:
    """Best-effort handoff after a chat parsing projection becomes terminal."""

    if document.source_kind != "chat_attachment":
        return []
    try:
        from app.conversation.application.attachment_waiting_service import (
            wake_attachment_turns_for_projection,
        )

        return wake_attachment_turns_for_projection(
            document.id, actions=attachment_resume_actions()
        )
    except Exception:  # noqa: BLE001 — parsing success/failure remains authoritative
        logger.exception(
            "Could not wake Turns waiting for attachment projection %s",
            document.id,
        )
        return []


@celery_app.task(
    bind=True,
    name="tasks.process_document_ingestion",
    autoretry_for=TRANSIENT_INGEST_ERRORS,
    retry_backoff=True,
    retry_backoff_max=120,
    retry_jitter=True,
    max_retries=3,
    acks_late=True,
    time_limit=1200,  # 20 min hard
    soft_time_limit=1140,
)
def process_document_ingestion(self, document_id: str):
    return execute_ingestion(
        document_id,
        task_id=self.request.id,
        retries=self.request.retries,
        max_retries=self.max_retries,
        session_factory=SessionLocal,
        wake_attachment_turns=_wake_attachment_turns,
    )
