"""Stale-lock recovery in the outbox drain (INF-5).

A worker SIGKILLed after the claim commit leaves its job at
status='running' with locked_at set — the finally block never runs.
The claim query must reclaim such jobs after 10 minutes (counting the
crashed attempt so a crash-looping handler can still reach ``dead``),
while never stealing a fresh running lock.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.models.outbox_job import OutboxJob
from app.services import outbox as outbox_service


def _enqueue(db, job_type: str, key: str) -> OutboxJob:
    job = outbox_service.enqueue_job(
        db,
        user_pk=1,
        job_type=job_type,
        aggregate_id=key,
    )
    db.commit()
    return job


def _orphan(db, job: OutboxJob, *, age: timedelta, attempts: int = 0) -> None:
    """Simulate a hard-killed worker: running + locked, no finally cleanup."""
    job.status = "running"
    job.locked_at = datetime.utcnow() - age
    job.locked_by = "dead-host:1"
    job.attempts = attempts
    db.add(job)
    db.commit()


def test_stale_running_job_is_reclaimed_and_rerun(db_session, monkeypatch):
    ran = []
    monkeypatch.setitem(
        outbox_service._HANDLERS,
        "t_reclaim",
        lambda db, job: ran.append(job.id),
    )
    job = _enqueue(db_session, "t_reclaim", "agg1")
    _orphan(db_session, job, age=timedelta(minutes=21))

    outbox_service.run_due_outbox_jobs(db_session)

    db_session.refresh(job)
    assert ran == [job.id]
    assert job.status == "succeeded"
    assert job.locked_at is None
    # The crashed attempt was counted.
    assert job.attempts == 1


def test_fresh_running_lock_is_not_stolen(db_session, monkeypatch):
    ran = []
    monkeypatch.setitem(
        outbox_service._HANDLERS,
        "t_fresh",
        lambda db, job: ran.append(job.id),
    )
    job = _enqueue(db_session, "t_fresh", "agg2")
    _orphan(db_session, job, age=timedelta(minutes=16))

    outbox_service.run_due_outbox_jobs(db_session)

    db_session.refresh(job)
    assert ran == []
    assert job.status == "running"  # still owned by the (presumed live) worker
    assert job.locked_by == "dead-host:1"


def test_crash_looping_job_reaches_dead_without_running(db_session, monkeypatch):
    ran = []
    monkeypatch.setitem(
        outbox_service._HANDLERS,
        "t_loop",
        lambda db, job: ran.append(job.id),
    )
    job = _enqueue(db_session, "t_loop", "agg3")
    # 4 prior attempts + this reclaim = max_attempts (5) → dead, not re-run.
    _orphan(db_session, job, age=timedelta(minutes=21), attempts=4)

    outbox_service.run_due_outbox_jobs(db_session)

    db_session.refresh(job)
    assert ran == []
    assert job.status == "dead"
    assert job.attempts == 5
    assert job.locked_at is None


def test_due_pending_job_still_claimed_alongside_reclaim(db_session, monkeypatch):
    ran = []
    monkeypatch.setitem(
        outbox_service._HANDLERS,
        "t_mix",
        lambda db, job: ran.append(job.id),
    )
    stale = _enqueue(db_session, "t_mix", "agg4")
    _orphan(db_session, stale, age=timedelta(minutes=21))
    fresh = _enqueue(db_session, "t_mix", "agg5")

    outbox_service.run_due_outbox_jobs(db_session)

    assert sorted(ran) == sorted([stale.id, fresh.id])
