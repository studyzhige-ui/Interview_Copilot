"""Stable application boundary for dispatching and revoking Celery tasks."""

from celery.result import AsyncResult

from app.task_queue.celery_app import celery_app


def dispatch_conversation_turn(turn_id: str) -> AsyncResult:
    return celery_app.send_task("tasks.process_conversation_turn", args=[turn_id])


def dispatch_interview_analysis(record_id: str, **kwargs) -> AsyncResult:
    return celery_app.send_task(
        "tasks.process_interview_analysis",
        args=[record_id],
        kwargs=kwargs,
    )


def dispatch_mock_interview_review(record_id: str) -> AsyncResult:
    return celery_app.send_task("tasks.process_mock_interview_review", args=[record_id])


def dispatch_document_ingestion(document_id: str) -> AsyncResult:
    return celery_app.send_task("tasks.process_document_ingestion", args=[document_id])


def dispatch_resume_parse(resume_id: str) -> AsyncResult:
    return celery_app.send_task("tasks.process_resume_parse", args=[resume_id])


def dispatch_outbox_drain(lane: str) -> AsyncResult:
    task_name = {
        "index": "tasks.drain_index_outbox_jobs",
        "intelligence": "tasks.drain_intelligence_outbox_jobs",
        "cleanup": "tasks.drain_cleanup_outbox_jobs",
    }.get(lane)
    if task_name is None:
        raise ValueError(f"Unknown outbox lane: {lane!r}")
    return celery_app.send_task(task_name)


def revoke_task(
    task_id: str,
    *,
    terminate: bool = False,
    signal: str | None = None,
) -> None:
    options = {"terminate": terminate}
    if signal:
        options["signal"] = signal
    celery_app.control.revoke(task_id, **options)


__all__ = [
    "dispatch_conversation_turn",
    "dispatch_document_ingestion",
    "dispatch_interview_analysis",
    "dispatch_mock_interview_review",
    "dispatch_outbox_drain",
    "dispatch_resume_parse",
    "revoke_task",
]
