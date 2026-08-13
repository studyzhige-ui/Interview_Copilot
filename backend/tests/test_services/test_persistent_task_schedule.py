from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.services.persistent_task_schedule import (
    ScheduleValidationError,
    next_cron_occurrence,
    validate_cron_schedule,
)


def test_cron_schedule_is_timezone_aware_and_strict() -> None:
    assert validate_cron_schedule(" 0 9 * * * ", "Asia/Shanghai") == (
        "0 9 * * *",
        "Asia/Shanghai",
    )
    assert next_cron_occurrence(
        "0 9 * * *",
        "Asia/Shanghai",
        datetime(2026, 8, 13, 0, 30, tzinfo=UTC),
    ) == datetime(2026, 8, 13, 1, 0, tzinfo=UTC)

    with pytest.raises(ScheduleValidationError, match="five cron fields"):
        validate_cron_schedule("@daily", "UTC")
    with pytest.raises(ScheduleValidationError, match="unknown IANA timezone"):
        validate_cron_schedule("0 9 * * *", "Mars/Olympus")

    assert next_cron_occurrence(
        "0 0 29 2 *",
        "UTC",
        datetime(2024, 2, 29, tzinfo=UTC),
    ) == datetime(2028, 2, 29, tzinfo=UTC)


@pytest.mark.parametrize("schedule", ["* * * * *", "0,59 * * * *", "*/4 * * * *"])
def test_cron_schedule_rejects_any_sub_five_minute_cadence(schedule: str) -> None:
    with pytest.raises(ScheduleValidationError, match="at least 5 minutes"):
        validate_cron_schedule(schedule, "UTC")


def test_minimum_frequency_does_not_assume_monthly_days_are_consecutive() -> None:
    assert validate_cron_schedule("0,59 0 1 * *", "UTC")[0] == "0,59 0 1 * *"
