"""Outbox jobs: reliable, retryable cross-system work.

Postgres is the transactional source of truth, but object storage and Milvus
are NOT in the same transaction. Anything that must happen to those external
systems after a committed business change — delete an object, drop a Milvus
index, clean up a failed upload, parse/ingest/transcribe — is enqueued here in
the SAME transaction as the business write, then drained by a worker.

Jobs are idempotent, retryable with backoff (``attempts`` / ``max_attempts`` /
``next_run_at``), observable (``status`` / ``last_error``), and lock-guarded so
two workers don't run the same job. The business read path never reads outbox
state as fact — it reads the business tables.

Keyed by the stable ``users.id`` (FK, ON DELETE CASCADE). ``aggregate_type`` /
``aggregate_id`` point at the business object the job acts on. Job-type-specific
parameters live in ``payload_json``.
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from app.db.database import Base


def generate_outbox_job_id() -> str:
    return f"job_{uuid.uuid4().hex}"


class OutboxJob(Base):
    __tablename__ = "outbox_jobs"
    __table_args__ = (
        # Worker claim scan: pending/failed jobs whose next_run_at is due.
        Index("ix_outbox_jobs_status_next_run", "status", "next_run_at"),
        # Idempotency: a (job_type, idempotency_key) pair enqueues once.
        UniqueConstraint(
            "job_type", "idempotency_key", name="uq_outbox_jobs_type_idem",
        ),
    )

    id = Column(String, primary_key=True, default=generate_outbox_job_id, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    # delete_object / delete_milvus_chunks / cleanup_failed_upload /
    # parse_resume / ingest_knowledge_document / transcribe_interview_audio /
    # parse_jd_snapshot / extract_memory_* / upsert|delete_memory_ability_index
    job_type = Column(String, index=True, nullable=False)
    aggregate_type = Column(String, nullable=True)
    aggregate_id = Column(String, nullable=True)
    payload_json = Column(Text, nullable=True)
    # pending -> running -> succeeded | failed (retryable) | dead (exhausted).
    status = Column(String, index=True, default="pending", nullable=False)
    attempts = Column(Integer, default=0, nullable=False)
    max_attempts = Column(Integer, default=5, nullable=False)
    next_run_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_error = Column(Text, nullable=True)
    # NULL when the job carries no natural idempotency key (the unique
    # constraint above only binds non-null keys per Postgres semantics).
    idempotency_key = Column(String, nullable=True)
    locked_at = Column(DateTime, nullable=True)
    locked_by = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False,
    )
