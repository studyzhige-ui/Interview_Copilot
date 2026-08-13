"""Celery tasks, one module per domain.

Task *names* (``tasks.<name>``) are frozen strings — the broker routes on
them (see ``celery_app.py`` ``task_routes`` / ``beat_schedule``) — so moving
a task between modules never changes its queue, schedule, or wire format.

Everything callers dispatch is re-exported here, so
``from app.worker.tasks import process_document_ingestion`` keeps working;
tests that patch module globals (e.g. ``SessionLocal``) must target the
submodule that owns the task.
"""

from app.worker.tasks.agent_memory import consolidate_agent_memory
from app.worker.tasks.catalog import refresh_model_catalog_task
from app.worker.tasks.chat import process_conversation_turn
from app.worker.tasks.ingestion import process_document_ingestion
from app.worker.tasks.gmail_observations import poll_gmail_observations
from app.worker.tasks.interview import (
    process_interview_analysis,
    process_mock_interview_review,
)
from app.worker.tasks.maintenance import (
    deliver_due_next_action_reminders,
    repair_pending_automation_turns,
    schedule_due_persistent_tasks,
    sweep_expired_conversation_deletion_receipts,
    sweep_orphan_file_assets,
    sweep_stale_interview_records,
    sweep_stale_pipeline_records,
)
from app.worker.tasks.outbox import (
    drain_cleanup_outbox_jobs,
    drain_index_outbox_jobs,
)
from app.worker.tasks.resume import process_resume_parse

__all__ = [
    "process_conversation_turn",
    "consolidate_agent_memory",
    "deliver_due_next_action_reminders",
    "process_interview_analysis",
    "process_mock_interview_review",
    "process_document_ingestion",
    "poll_gmail_observations",
    "process_resume_parse",
    "refresh_model_catalog_task",
    "repair_pending_automation_turns",
    "schedule_due_persistent_tasks",
    "sweep_expired_conversation_deletion_receipts",
    "drain_cleanup_outbox_jobs",
    "drain_index_outbox_jobs",
    "sweep_orphan_file_assets",
    "sweep_stale_interview_records",
    "sweep_stale_pipeline_records",
]
