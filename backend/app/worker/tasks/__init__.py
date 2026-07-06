"""Celery tasks, one module per domain.

Task *names* (``tasks.<name>``) are frozen strings — the broker routes on
them (see ``celery_app.py`` ``task_routes`` / ``beat_schedule``) — so moving
a task between modules never changes its queue, schedule, or wire format.

Everything callers dispatch is re-exported here, so
``from app.worker.tasks import process_document_ingestion`` keeps working;
tests that patch module globals (e.g. ``SessionLocal``) must target the
submodule that owns the task.
"""
from app.worker.tasks.runtime import run_async
from app.worker.tasks.interview import process_interview_analysis
from app.worker.tasks.ingestion import process_document_ingestion
from app.worker.tasks.resume import process_resume_parse
from app.worker.tasks.memory import dream_for_user_task, scan_and_dream_batch_task
from app.worker.tasks.catalog import refresh_model_catalog_task
from app.worker.tasks.outbox import drain_outbox_jobs
from app.worker.tasks.maintenance import sweep_stale_interview_records

__all__ = [
    "run_async",
    "process_interview_analysis",
    "process_document_ingestion",
    "process_resume_parse",
    "dream_for_user_task",
    "scan_and_dream_batch_task",
    "refresh_model_catalog_task",
    "drain_outbox_jobs",
    "sweep_stale_interview_records",
]
