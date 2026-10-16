"""Scheduled tasks reuse one conversation and retain triggers behind active work."""

from datetime import UTC, datetime, timedelta

import pytest

from app.automation.application import tasks
from app.core.cron_schedule import next_cron_occurrence, validate_cron_schedule
from app.models.persistent_task import PersistentTaskTrigger
from app.schemas.persistent_task import (
    PersistentTaskCreate,
    PersistentTaskStateChange,
    PersistentTaskTriggerInput,
)


@pytest.mark.parametrize(
    "schedule, zone, after, expected",
    [
        (
            "0 9 * * *",
            "Asia/Shanghai",
            "2030-01-01T01:00:00+00:00",
            "2030-01-02T01:00:00+00:00",
        ),
        (
            "30 2 * * *",
            "America/New_York",
            "2026-03-08T05:00:00+00:00",
            "2026-03-09T06:30:00+00:00",
        ),
        (
            "30 1 * * *",
            "America/New_York",
            "2026-11-01T05:30:00+00:00",
            "2026-11-02T06:30:00+00:00",
        ),
        ("0 0 29 2 *", "UTC", "2025-01-01T00:00:00+00:00", "2028-02-29T00:00:00+00:00"),
    ],
)
def test_schedule_timezone_dst_and_leap_day(schedule, zone, after, expected):
    assert next_cron_occurrence(
        schedule, zone, datetime.fromisoformat(after)
    ) == datetime.fromisoformat(expected)


@pytest.mark.parametrize("schedule", ["* * * * *", "60 * * * *", "0 0 31 2 *"])
def test_invalid_or_excessively_frequent_schedules_are_rejected(schedule):
    with pytest.raises(ValueError):
        validate_cron_schedule(schedule, "UTC")


def test_schedule_replay_pause_ownership_and_active_turn_arbitration(
    db, owners, monkeypatch
):
    owner, other = owners
    now = datetime(2030, 1, 1, tzinfo=UTC)
    monkeypatch.setattr(tasks, "utc_now", lambda: now)
    command = PersistentTaskCreate(
        title="Daily review",
        instruction="Summarize existing notes",
        trigger={"kind": "scheduled", "schedule": "*/5 * * * *", "timezone": "UTC"},
        user_request_identity="explicit-test",
        idempotency_key=" daily-review ",
    )
    create = dict(user_pk=owner.id, command=command, cloud_sustainable_tool_names=[])
    task = tasks.create_persistent_task(db, **create)
    assert tasks.create_persistent_task(db, **create).id == task.id
    manual = PersistentTaskTriggerInput(
        kind="manual",
        occurred_at=now,
        source_identity="user-request",
        summary="Review now",
        idempotency_key=" manual-run ",
    )
    intake = dict(
        user_pk=owner.id,
        task_id=task.id,
        command=manual,
        cloud_sustainable_tool_names=[],
        attempt_admission=False,
    )
    initial_trigger = tasks.intake_persistent_task_trigger(db, **intake)
    assert (
        tasks.intake_persistent_task_trigger(db, **intake).trigger_id
        == initial_trigger.trigger_id
    )
    with pytest.raises(tasks.PersistentTaskNotFoundError):
        tasks.get_persistent_task(db, user_pk=other.id, task_id=task.id)
    first_due = now + timedelta(minutes=5)
    schedule = dict(task_id=task.id, cloud_sustainable_tool_names=[])
    first = tasks.schedule_due_persistent_task(db, **schedule, due_at=first_due)
    assert first.should_dispatch
    assert tasks.schedule_due_persistent_task(db, **schedule, due_at=first_due) is None
    pending = tasks.schedule_due_persistent_task(
        db, **schedule, due_at=first_due + timedelta(minutes=5)
    )
    assert pending.reason == "active_or_waiting_turn" and not pending.should_dispatch
    assert (
        db.query(PersistentTaskTrigger).filter_by(persistent_task_id=task.id).count()
        == 3
    )
    tasks.change_persistent_task_state(
        db,
        user_pk=owner.id,
        task_id=task.id,
        command=PersistentTaskStateChange(
            expected_version=task.version, state="paused", user_request_identity="pause"
        ),
    )
    assert (
        tasks.schedule_due_persistent_task(
            db, **schedule, due_at=first_due + timedelta(hours=1)
        )
        is None
    )
