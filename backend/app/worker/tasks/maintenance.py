"""Beat-driven DB sweepers (light queue) — the terminal-state guarantee of
last resort for rows nothing else re-examines.

* ``sweep_stale_interview_records`` — interview records stuck in an
  in-flight status (lost broker message, dead worker).
* ``sweep_stale_pipeline_records`` — re-dispatch knowledge/resume Artifact work
  whose broker message disappeared before producing durable facts.
* ``sweep_orphan_file_assets`` — presigned uploads whose client vanished
  before confirm/consume.
* ``sweep_expired_conversation_deletion_receipts`` — bounded cleanup of the
  minimal receipt correlations retained after Conversation deletion.
"""

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.core.config import settings
from app.db.database import SessionLocal
from app.db.types import utc_now
from app.task_queue.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="tasks.sweep_stale_interview_records",
    time_limit=60,
    soft_time_limit=50,
)
def sweep_stale_interview_records(self):
    """Schedule the bounded domain recovery command."""
    from app.interviews.application.stale_recovery import expire_stale_reviews

    with SessionLocal() as db:
        swept = expire_stale_reviews(db, now=utc_now())
        db.commit()
    return {"swept": swept}


_PIPELINE_STALE_AFTER = timedelta(hours=2)
_AUTOMATION_DISPATCH_REPAIR_AFTER = timedelta(minutes=1)


@celery_app.task(
    name="tasks.sweep_expired_conversation_deletion_receipts",
    time_limit=60,
    soft_time_limit=50,
)
def sweep_expired_conversation_deletion_receipts():
    """Purge only expired Conversation-deletion receipt tombstones."""

    from app.conversation.application.conversation_deletion_service import (
        purge_expired_conversation_deletion_receipts,
    )

    with SessionLocal() as db:
        purged = purge_expired_conversation_deletion_receipts(
            db,
            due_at=utc_now(),
            limit=500,
        )
        db.commit()
    return {"purged": purged}


@celery_app.task(
    name="tasks.deliver_due_next_action_reminders",
    time_limit=60,
    soft_time_limit=50,
)
def deliver_due_next_action_reminders():
    """Materialize due in-app deliveries while respecting user quiet hours."""

    from app.career.application.reminders import deliver_due_reminders

    with SessionLocal() as db:
        result = deliver_due_reminders(db, due_at=utc_now(), limit=200)
        db.commit()
        return result


@celery_app.task(
    name="tasks.schedule_due_persistent_tasks",
    time_limit=60,
    soft_time_limit=50,
)
def schedule_due_persistent_tasks():
    """Boundedly persist due cron occurrences, then dispatch admitted Turns."""

    from app.agent_runtime.turn_tool_catalog import (
        cloud_sustainable_automation_tool_names,
    )
    from app.automation.application.tasks import due_persistent_task_ids
    from app.automation.application.tasks import schedule_due_persistent_task
    from app.task_queue.dispatch import dispatch_conversation_turn

    due_at = utc_now()
    with SessionLocal() as db:
        task_ids = due_persistent_task_ids(db, due_at=due_at, limit=100)
    triggered = 0
    admitted = 0
    dispatched = 0
    for task_id in task_ids:
        with SessionLocal() as db:
            try:
                admission = schedule_due_persistent_task(
                    db,
                    task_id=task_id,
                    due_at=due_at,
                    cloud_sustainable_tool_names=(
                        cloud_sustainable_automation_tool_names()
                    ),
                )
                db.commit()
            except Exception:  # noqa: BLE001 - one schedule cannot block the batch
                db.rollback()
                logger.warning(
                    "scheduled PersistentTask intake failed for %s",
                    task_id,
                    exc_info=True,
                )
                continue
        if admission is None:
            continue
        triggered += 1
        if admission.should_dispatch and admission.run_request is not None:
            admitted += 1
            try:
                dispatch_conversation_turn(admission.run_request.turn_id)
            except Exception:  # noqa: BLE001 - durable repair re-dispatches it
                logger.warning(
                    "scheduled PersistentTask dispatch deferred for %s",
                    admission.run_request.turn_id,
                    exc_info=True,
                )
            else:
                dispatched += 1
    return {
        "candidates": len(task_ids),
        "triggered": triggered,
        "admitted": admitted,
        "dispatched": dispatched,
    }


@celery_app.task(
    name="tasks.repair_pending_automation_turns",
    time_limit=60,
    soft_time_limit=50,
)
def repair_pending_automation_turns():
    """Boundedly re-dispatch admitted automation Turns after broker loss."""

    from app.automation.application.tasks import admit_pending_persistent_task_triggers
    from app.automation.application.tasks import repairable_automation_turn_ids
    from app.automation.application.tasks import repairable_persistent_task_ids
    from app.agent_runtime.turn_tool_catalog import (
        cloud_sustainable_automation_tool_names,
    )
    from app.models.persistent_task import PersistentTask
    from app.task_queue.dispatch import dispatch_conversation_turn

    with SessionLocal() as db:
        turn_ids = repairable_automation_turn_ids(
            db,
            stale_before=utc_now() - _AUTOMATION_DISPATCH_REPAIR_AFTER,
            limit=100,
        )
        task_ids = repairable_persistent_task_ids(db, limit=100)
    dispatched = 0
    for turn_id in turn_ids:
        try:
            dispatch_conversation_turn(turn_id)
        except Exception:  # noqa: BLE001 - next bounded sweep retries it
            logger.warning(
                "automation Turn repair dispatch failed for %s",
                turn_id,
                exc_info=True,
            )
        else:
            dispatched += 1
    admitted = 0
    for task_id in task_ids:
        with SessionLocal() as db:
            task = db.get(PersistentTask, task_id)
            if task is None:
                continue
            try:
                admission = admit_pending_persistent_task_triggers(
                    db,
                    user_pk=task.user_id,
                    task_id=task.id,
                    cloud_sustainable_tool_names=(
                        cloud_sustainable_automation_tool_names()
                    ),
                )
                db.commit()
            except Exception:  # noqa: BLE001 - one definition cannot block the batch
                db.rollback()
                logger.warning(
                    "automation trigger admission repair failed for %s",
                    task_id,
                    exc_info=True,
                )
                continue
        if admission.should_dispatch and admission.run_request is not None:
            admitted += 1
            try:
                dispatch_conversation_turn(admission.run_request.turn_id)
            except Exception:  # noqa: BLE001 - pending Turn repair handles it later
                logger.warning(
                    "repaired automation admission dispatch failed for %s",
                    admission.run_request.turn_id,
                    exc_info=True,
                )
            else:
                dispatched += 1
    return {
        "turn_candidates": len(turn_ids),
        "task_candidates": len(task_ids),
        "admitted": admitted,
        "dispatched": dispatched,
    }


@celery_app.task(
    bind=True,
    name="tasks.sweep_stale_pipeline_records",
    time_limit=60,
    soft_time_limit=50,
)
def sweep_stale_pipeline_records(self):
    """Re-dispatch stale canonical parse/ingest rows."""
    from app.models.artifact import Artifact, ArtifactResumeState
    from app.models.document_chunk import DocumentChunk
    from app.models.knowledge import KnowledgeDocument
    from app.worker.tasks.ingestion import process_document_ingestion
    from app.worker.tasks.resume import process_resume_parse

    cutoff = utc_now() - _PIPELINE_STALE_AFTER
    dispatched = 0
    with SessionLocal() as db:
        documents = (
            db.query(KnowledgeDocument)
            .filter(
                KnowledgeDocument.status == "processing",
                KnowledgeDocument.updated_at < cutoff,
                KnowledgeDocument.deleted_at.is_(None),
                ~db.query(DocumentChunk.id)
                .filter(DocumentChunk.document_id == KnowledgeDocument.id)
                .exists(),
            )
            .limit(100)
            .all()
        )
        resumes = (
            db.query(ArtifactResumeState)
            .join(Artifact, Artifact.id == ArtifactResumeState.artifact_id)
            .filter(
                Artifact.kind == "resume",
                Artifact.archived_at.is_(None),
                ArtifactResumeState.parse_status.in_(("pending", "processing")),
                ArtifactResumeState.updated_at < cutoff,
            )
            .order_by(ArtifactResumeState.updated_at.asc())
            .limit(100)
            .all()
        )

        for document in documents:
            try:
                task = process_document_ingestion.delay(document.id)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "stale knowledge re-dispatch failed for %s: %s",
                    document.id,
                    exc,
                )
                continue
            from app.rag.application.document_commands import record_ingestion_dispatch

            record_ingestion_dispatch(
                db, document_id=document.id, task_id=task.id, now=utc_now()
            )
            dispatched += 1

        for resume in resumes:
            try:
                process_resume_parse.delay(resume.artifact_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "stale resume re-dispatch failed for %s: %s",
                    resume.artifact_id,
                    exc,
                )
                continue
            from app.career.application.resumes.resume_dispatch_service import (
                record_parse_dispatch,
            )

            record_parse_dispatch(db, artifact_id=resume.artifact_id, now=utc_now())
            dispatched += 1
        db.commit()
    return {
        "dispatched": dispatched,
        "knowledge": len(documents),
        "resumes": len(resumes),
    }


@celery_app.task(
    bind=True,
    name="tasks.sweep_orphan_file_assets",
    time_limit=120,
    soft_time_limit=100,
)
def sweep_orphan_file_assets(self):
    """Schedule the owned, bounded orphan cleanup command."""
    from app.files.application.cleanup import expire_orphan_uploads

    with SessionLocal() as db:
        swept = expire_orphan_uploads(db, now=utc_now())
        db.commit()
    return {"swept": swept}


_TEMP_FILE_TTL = timedelta(hours=24)
_DEV_LOG_TTL = timedelta(days=14)


def _remove_files_older_than(root: Path, pattern: str, cutoff: datetime) -> int:
    if not root.is_dir():
        return 0
    removed = 0
    for path in root.rglob(pattern):
        try:
            modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
            if path.is_file() and modified_at < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            logger.warning("runtime-file cleanup failed for %s", path, exc_info=True)
    return removed


@celery_app.task(
    name="tasks.sweep_runtime_files",
    time_limit=120,
    soft_time_limit=100,
)
def sweep_runtime_files():
    """Bound disposable local files without touching model or user-data caches."""
    now = utc_now()
    data_dir = Path(settings.APP_DATA_DIR)
    temp_files = _remove_files_older_than(data_dir / "tmp", "*", now - _TEMP_FILE_TTL)
    dev_logs = _remove_files_older_than(
        Path(settings.LOG_DIR), "*.log", now - _DEV_LOG_TTL
    )

    return {
        "temp_files": temp_files,
        "dev_logs": dev_logs,
    }
