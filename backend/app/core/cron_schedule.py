"""Small, strict five-field cron evaluator for PersistentTask scheduling.

The product deliberately accepts a narrow, auditable cron surface instead of
silently depending on platform-specific cron extensions.  All evaluation is
performed from UTC instants through an IANA timezone so DST transitions remain
deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


MIN_SCHEDULE_INTERVAL = timedelta(minutes=5)
_SEARCH_LIMIT_DAYS = 366 * 5


class ScheduleValidationError(ValueError):
    """A schedule cannot be evaluated safely by the cloud scheduler."""


@dataclass(frozen=True)
class _CronFields:
    minute: frozenset[int]
    hour: frozenset[int]
    day: frozenset[int]
    month: frozenset[int]
    weekday: frozenset[int]
    day_wildcard: bool
    weekday_wildcard: bool


def validate_cron_schedule(schedule: str, timezone_name: str) -> tuple[str, str]:
    """Validate and normalize a cloud schedule, including its minimum cadence."""

    normalized_schedule = " ".join(schedule.strip().split())
    normalized_timezone = timezone_name.strip()
    fields = _parse(normalized_schedule)
    _timezone(normalized_timezone)
    anchor = datetime(2024, 1, 1, tzinfo=UTC)
    _next(fields, normalized_timezone, anchor)
    if _minimum_time_of_day_gap(fields) < MIN_SCHEDULE_INTERVAL:
        raise ScheduleValidationError("schedule frequency must be at least 5 minutes")
    return normalized_schedule, normalized_timezone


def next_cron_occurrence(
    schedule: str,
    timezone_name: str,
    after: datetime,
) -> datetime:
    """Return the first occurrence strictly after ``after`` as an aware UTC value."""

    normalized_schedule = " ".join(schedule.strip().split())
    normalized_timezone = timezone_name.strip()
    fields = _parse(normalized_schedule)
    _timezone(normalized_timezone)
    if _minimum_time_of_day_gap(fields) < MIN_SCHEDULE_INTERVAL:
        raise ScheduleValidationError("schedule frequency must be at least 5 minutes")
    return _next(fields, normalized_timezone, after)


def _timezone(name: str) -> ZoneInfo:
    if not name:
        raise ScheduleValidationError("timezone must not be empty")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ScheduleValidationError(f"unknown IANA timezone: {name}") from exc


def _parse(schedule: str) -> _CronFields:
    parts = schedule.split()
    if len(parts) != 5:
        raise ScheduleValidationError("schedule must use five cron fields")
    minute, minute_wild = _field(parts[0], 0, 59, "minute")
    hour, hour_wild = _field(parts[1], 0, 23, "hour")
    day, day_wild = _field(parts[2], 1, 31, "day-of-month")
    month, month_wild = _field(parts[3], 1, 12, "month")
    weekday, weekday_wild = _field(parts[4], 0, 7, "day-of-week")
    del minute_wild, hour_wild, month_wild
    weekday = frozenset(0 if value == 7 else value for value in weekday)
    return _CronFields(
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        weekday=weekday,
        day_wildcard=day_wild,
        weekday_wildcard=weekday_wild,
    )


def _field(
    raw: str,
    minimum: int,
    maximum: int,
    name: str,
) -> tuple[frozenset[int], bool]:
    values: set[int] = set()
    for item in raw.split(","):
        if not item:
            raise ScheduleValidationError(f"invalid {name} field")
        base, separator, step_text = item.partition("/")
        step = 1
        if separator:
            if not step_text.isdigit() or int(step_text) < 1:
                raise ScheduleValidationError(f"invalid {name} step")
            step = int(step_text)
        if base == "*":
            start, end = minimum, maximum
        elif "-" in base:
            start_text, end_text = base.split("-", 1)
            if not start_text.isdigit() or not end_text.isdigit():
                raise ScheduleValidationError(f"invalid {name} range")
            start, end = int(start_text), int(end_text)
        elif base.isdigit():
            start = end = int(base)
            if separator:
                end = maximum
        else:
            raise ScheduleValidationError(f"invalid {name} field")
        if start < minimum or end > maximum or start > end:
            raise ScheduleValidationError(f"{name} value is out of range")
        values.update(range(start, end + 1, step))
    return frozenset(values), raw == "*"


def _next(fields: _CronFields, timezone_name: str, after: datetime) -> datetime:
    if after.tzinfo is None:
        after = after.replace(tzinfo=UTC)
    timezone = _timezone(timezone_name)
    after_utc = after.astimezone(UTC)
    first_local_date = after_utc.astimezone(timezone).date()
    times = sorted((hour, minute) for hour in fields.hour for minute in fields.minute)
    for day_offset in range(_SEARCH_LIMIT_DAYS + 1):
        local_date = first_local_date + timedelta(days=day_offset)
        if not _calendar_day_matches(fields, local_date):
            continue
        for hour, minute in times:
            local = datetime(
                local_date.year,
                local_date.month,
                local_date.day,
                hour,
                minute,
                tzinfo=timezone,
            )
            candidate = local.astimezone(UTC)
            # A spring-forward wall time is not real. Round-tripping detects
            # it; an ambiguous fall-back time intentionally fires once.
            round_trip = candidate.astimezone(timezone)
            if (
                round_trip.date() != local_date
                or round_trip.hour != hour
                or round_trip.minute != minute
            ):
                continue
            if candidate > after_utc:
                return candidate
    raise ScheduleValidationError("schedule has no occurrence within five years")


def _minimum_time_of_day_gap(fields: _CronFields) -> timedelta:
    times = sorted(
        hour * 60 + minute for hour in fields.hour for minute in fields.minute
    )
    if len(times) == 1:
        return timedelta(days=1)
    gaps = [later - earlier for earlier, later in zip(times, times[1:])]
    if _has_consecutive_calendar_days(fields):
        gaps.append(24 * 60 - times[-1] + times[0])
    return timedelta(minutes=min(gaps))


def _calendar_day_matches(fields: _CronFields, value: date) -> bool:
    if value.month not in fields.month:
        return False
    cron_weekday = (value.weekday() + 1) % 7
    day_matches = value.day in fields.day
    weekday_matches = cron_weekday in fields.weekday
    if fields.day_wildcard:
        return weekday_matches
    if fields.weekday_wildcard:
        return day_matches
    return day_matches or weekday_matches


def _has_consecutive_calendar_days(fields: _CronFields) -> bool:
    cursor = datetime(2024, 1, 1).date()
    previous = False
    for day_offset in range(400):
        matches = _calendar_day_matches(fields, cursor + timedelta(days=day_offset))
        if matches and previous:
            return True
        previous = matches
    return False


__all__ = [
    "MIN_SCHEDULE_INTERVAL",
    "ScheduleValidationError",
    "next_cron_occurrence",
    "validate_cron_schedule",
]
