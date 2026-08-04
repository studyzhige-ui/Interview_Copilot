"""Worker handlers for durable memory extraction jobs."""

import json

from sqlalchemy.orm import Session

from app.models.outbox_job import OutboxJob
from app.services.memory.extraction_jobs import DREAMING_JOB, REALTIME_JOB
from app.services.outbox import register_handler


def handle_realtime(db: Session, job: OutboxJob) -> None:
    from app.services.memory.realtime_extraction import run_realtime_extraction

    payload = json.loads(job.payload_json) if job.payload_json else {}
    session_id = payload.get("session_id")
    user_id = payload.get("user_id")
    upto_seq = payload.get("upto_seq")
    if not session_id or not user_id or upto_seq is None:
        raise ValueError(f"{REALTIME_JOB}: bad payload {payload}")
    if job.aggregate_id and job.aggregate_id != session_id:
        raise ValueError("memory-extraction aggregate id does not match payload")
    from app.models.chat import Conversation
    from app.models.user import User

    conversation_owner = (
        db.query(Conversation.user_id).filter(Conversation.id == session_id).scalar()
    )
    if conversation_owner is None:
        return
    if conversation_owner != job.user_id:
        raise PermissionError("memory-extraction job owner does not match conversation")
    owner_username = db.query(User.username).filter(User.id == job.user_id).scalar()
    if owner_username != user_id:
        raise PermissionError(
            "memory-extraction job owner does not match payload owner"
        )
    run_realtime_extraction(
        session_id=session_id,
        user_id=user_id,
        record_id=payload.get("record_id"),
        upto_seq=int(upto_seq),
    )


def handle_dreaming(db: Session, job: OutboxJob) -> None:
    from app.services.memory.dreaming_worker import dream_for_record

    payload = json.loads(job.payload_json) if job.payload_json else {}
    record_id = payload.get("record_id")
    if not record_id:
        raise ValueError(f"{DREAMING_JOB}: bad payload {payload}")
    if job.aggregate_id and job.aggregate_id != record_id:
        raise ValueError("dreaming aggregate id does not match payload")
    from app.models.interview_record import InterviewRecord

    record_owner = (
        db.query(InterviewRecord.user_id)
        .filter(InterviewRecord.id == record_id)
        .scalar()
    )
    if record_owner is None:
        return
    if record_owner != job.user_id:
        raise PermissionError("dreaming job owner does not match interview record")
    summary = dream_for_record(record_id)
    if summary.get("error"):
        raise RuntimeError(f"dreaming failed for {record_id}: {summary['error']}")


def handle_dream_check_user(db: Session, job: OutboxJob) -> None:
    """Dispatch an immediate Celery dream task after the durable quiet window."""
    from app.worker.tasks.memory import dream_for_user_task

    payload = json.loads(job.payload_json) if job.payload_json else {}
    username = payload.get("username")
    if not username:
        raise ValueError(f"dream_check_user: bad payload {payload}")
    from app.models.user import User

    owner_username = db.query(User.username).filter(User.id == job.user_id).scalar()
    if owner_username != username:
        raise PermissionError("dream-check job owner does not match payload owner")
    dream_for_user_task.delay(username)


register_handler(REALTIME_JOB, handle_realtime)
register_handler(DREAMING_JOB, handle_dreaming)
register_handler("dream_check_user", handle_dream_check_user)

__all__ = ["handle_dream_check_user", "handle_dreaming", "handle_realtime"]
