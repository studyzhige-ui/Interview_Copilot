"""Notification scheduling and deterministic NextAction agenda projection."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from app.db.types import as_utc, utc_now
from app.models.job_opportunity import NextAction
from app.models.notification_preference import NotificationPreference
from app.schemas.career_insights import (
    NextActionAgenda,
    NextActionAgendaItem,
    NotificationPreferenceUpdate,
)
from app.schemas.job_opportunity import NextActionView


class ReminderError(ValueError):
    pass


class ReminderConflictError(ReminderError):
    pass


class ReminderNotFoundError(ReminderError):
    pass


def notification_preference(db: Session, *, user_pk: int) -> NotificationPreference:
    row = db.get(NotificationPreference, user_pk)
    if row is not None:
        return row
    # Transient defaults are visible but do not create state on read.
    return NotificationPreference(
        user_id=user_pk,
        enabled=True,
        default_channel="in_app",
        timezone="Asia/Shanghai",
        quiet_start=None,
        quiet_end=None,
        version=0,
    )


def update_notification_preference(
    db: Session,
    *,
    user_pk: int,
    command: NotificationPreferenceUpdate,
) -> NotificationPreference:
    try:
        ZoneInfo(command.timezone)
    except ZoneInfoNotFoundError as exc:
        raise ReminderError("timezone must be a valid IANA timezone") from exc

    row = (
        db.query(NotificationPreference)
        .filter(NotificationPreference.user_id == user_pk)
        .with_for_update()
        .one_or_none()
    )
    current_version = int(row.version) if row is not None else 0
    if command.expected_version != current_version:
        raise ReminderConflictError(
            f"expected notification preference version {command.expected_version}, "
            f"current version is {current_version}"
        )
    if row is None:
        row = NotificationPreference(user_id=user_pk)
    row.enabled = command.enabled
    row.default_channel = command.default_channel
    row.timezone = command.timezone
    row.quiet_start = command.quiet_start
    row.quiet_end = command.quiet_end
    row.version = current_version + 1
    row.updated_at = utc_now()
    db.add(row)

    if command.enabled:
        # Re-enable due reminders immediately instead of waiting for a prior
        # disabled-setting backoff to expire.
        db.query(NextAction).filter(
            NextAction.user_id == user_pk,
            NextAction.status == "planned",
            NextAction.reminder_at.is_not(None),
            NextAction.reminder_delivered_at.is_(None),
        ).update(
            {NextAction.reminder_next_attempt_at: NextAction.reminder_at},
            synchronize_session=False,
        )
    db.flush()
    return row


def deliver_due_reminders(
    db: Session,
    *,
    due_at: datetime | None = None,
    limit: int = 200,
) -> dict[str, int]:
    """Stamp bounded in-app deliveries; safe to run every minute."""

    now = as_utc(due_at) or utc_now()
    rows = (
        db.query(NextAction)
        .filter(
            NextAction.status == "planned",
            NextAction.reminder_channel == "in_app",
            NextAction.reminder_delivered_at.is_(None),
            NextAction.reminder_next_attempt_at <= now,
        )
        .order_by(NextAction.reminder_next_attempt_at.asc(), NextAction.id.asc())
        .with_for_update(skip_locked=True)
        .limit(max(1, min(limit, 500)))
        .all()
    )
    delivered = 0
    deferred_quiet = 0
    deferred_disabled = 0
    for action in rows:
        preference = db.get(NotificationPreference, action.user_id)
        if preference is not None and not preference.enabled:
            action.reminder_next_attempt_at = now + timedelta(hours=1)
            deferred_disabled += 1
        else:
            timezone = (
                preference.timezone if preference is not None else "Asia/Shanghai"
            )
            quiet_start = preference.quiet_start if preference is not None else None
            quiet_end = preference.quiet_end if preference is not None else None
            next_allowed = _next_allowed_delivery(
                now,
                timezone=timezone,
                quiet_start=quiet_start,
                quiet_end=quiet_end,
            )
            if next_allowed > now:
                action.reminder_next_attempt_at = next_allowed
                deferred_quiet += 1
            else:
                action.reminder_delivered_at = now
                delivered += 1
        action.version += 1
        action.updated_at = now
        db.add(action)
    db.flush()
    return {
        "candidates": len(rows),
        "delivered": delivered,
        "deferred_quiet": deferred_quiet,
        "deferred_disabled": deferred_disabled,
    }


def list_reminder_inbox(
    db: Session,
    *,
    user_pk: int,
    limit: int = 50,
) -> list[NextAction]:
    return (
        db.query(NextAction)
        .filter(
            NextAction.user_id == user_pk,
            NextAction.reminder_delivered_at.is_not(None),
            NextAction.reminder_dismissed_at.is_(None),
        )
        .order_by(NextAction.reminder_delivered_at.desc(), NextAction.id.asc())
        .limit(max(1, min(limit, 200)))
        .all()
    )


def dismiss_reminder(
    db: Session,
    *,
    user_pk: int,
    action_id: str,
    expected_version: int,
) -> NextAction:
    action = (
        db.query(NextAction)
        .filter(NextAction.id == action_id, NextAction.user_id == user_pk)
        .with_for_update()
        .one_or_none()
    )
    if action is None:
        raise ReminderNotFoundError(action_id)
    if action.version != expected_version:
        raise ReminderConflictError(
            f"expected action version {expected_version}, current version is {action.version}"
        )
    if action.reminder_delivered_at is None:
        raise ReminderConflictError("the reminder has not been delivered")
    if action.reminder_dismissed_at is None:
        action.reminder_dismissed_at = utc_now()
        action.version += 1
        action.updated_at = utc_now()
        db.add(action)
        db.flush()
    return action


def build_next_action_agenda(
    db: Session,
    *,
    user_pk: int,
    at: datetime | None = None,
) -> NextActionAgenda:
    now = as_utc(at) or utc_now()
    preference = db.get(NotificationPreference, user_pk)
    try:
        user_zone = ZoneInfo(
            preference.timezone if preference is not None else "Asia/Shanghai"
        )
    except ZoneInfoNotFoundError:
        user_zone = ZoneInfo("UTC")
    local_today = now.astimezone(user_zone).date()
    actions = (
        db.query(NextAction)
        .filter(
            NextAction.user_id == user_pk,
            NextAction.status.in_(("suggested", "planned")),
        )
        .all()
    )
    conflicts: dict[str, set[str]] = {action.id: set() for action in actions}
    duplicates: dict[str, set[str]] = {action.id: set() for action in actions}
    for index, left in enumerate(actions):
        for right in actions[index + 1 :]:
            if _actions_conflict(left, right):
                conflicts[left.id].add(right.id)
                conflicts[right.id].add(left.id)
            if _actions_duplicate(left, right):
                duplicates[left.id].add(right.id)
                duplicates[right.id].add(left.id)

    items: list[NextActionAgendaItem] = []
    for action in actions:
        anchor = action.starts_at if action.time_kind == "fixed" else action.due_at
        anchor = as_utc(anchor)
        overdue = bool(action.time_kind == "deadline" and anchor and anchor < now)
        due_soon = bool(anchor and now <= anchor <= now + timedelta(hours=72))
        if conflicts[action.id]:
            bucket = "conflict"
        elif anchor and anchor.astimezone(user_zone).date() == local_today:
            bucket = "today"
        elif anchor:
            bucket = "upcoming"
        elif action.status == "planned":
            bucket = "unscheduled_planned"
        else:
            bucket = "suggested"
        items.append(
            NextActionAgendaItem(
                action=NextActionView.model_validate(action),
                bucket=bucket,
                overdue=overdue,
                due_soon=due_soon,
                conflict_action_ids=sorted(conflicts[action.id]),
                duplicate_action_ids=sorted(duplicates[action.id]),
            )
        )
    rank = {
        "conflict": 0,
        "today": 1,
        "upcoming": 2,
        "unscheduled_planned": 3,
        "suggested": 4,
    }
    items.sort(
        key=lambda item: (
            rank[item.bucket],
            as_utc(
                item.action.starts_at
                if item.action.time_kind == "fixed"
                else item.action.due_at
            )
            or datetime.max.replace(tzinfo=UTC),
            item.action.id,
        )
    )
    return NextActionAgenda(generated_at=now, items=items)


def _actions_conflict(left: NextAction, right: NextAction) -> bool:
    if left.time_kind == right.time_kind == "fixed":
        left_start = as_utc(left.starts_at)
        right_start = as_utc(right.starts_at)
        if left_start is None or right_start is None:
            return False
        left_end = as_utc(left.ends_at) or left_start
        right_end = as_utc(right.ends_at) or right_start
        if left_end == left_start and right_end == right_start:
            return left_start == right_start
        if left_end == left_start:
            return right_start <= left_start <= right_end
        if right_end == right_start:
            return left_start <= right_start <= left_end
        return left_start < right_end and right_start < left_end
    fixed = (
        left
        if left.time_kind == "fixed"
        else right
        if right.time_kind == "fixed"
        else None
    )
    deadline = (
        left
        if left.time_kind == "deadline"
        else right
        if right.time_kind == "deadline"
        else None
    )
    if fixed is None or deadline is None:
        return False
    start = as_utc(fixed.starts_at)
    end = as_utc(fixed.ends_at) or start
    due = as_utc(deadline.due_at)
    return bool(start and end and due and start <= due <= end)


def _actions_duplicate(left: NextAction, right: NextAction) -> bool:
    return (
        " ".join(left.content.casefold().split())
        == " ".join(right.content.casefold().split())
        and left.job_opportunity_id == right.job_opportunity_id
        and left.interview_record_id == right.interview_record_id
        and left.offer_id == right.offer_id
        and left.artifact_id == right.artifact_id
        # The same follow-up on different dates is usually recurring work, not
        # a duplicate reminder.  Duplicate detection is intentionally strict
        # and deterministic instead of relying on fuzzy semantic similarity.
        and left.time_kind == right.time_kind
        and as_utc(left.starts_at) == as_utc(right.starts_at)
        and as_utc(left.ends_at) == as_utc(right.ends_at)
        and as_utc(left.due_at) == as_utc(right.due_at)
    )


def _next_allowed_delivery(
    now: datetime,
    *,
    timezone: str,
    quiet_start: str | None,
    quiet_end: str | None,
) -> datetime:
    if quiet_start is None or quiet_end is None:
        return now
    try:
        zone = ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        zone = ZoneInfo("UTC")
    local = now.astimezone(zone)
    start_value = time.fromisoformat(quiet_start)
    end_value = time.fromisoformat(quiet_end)
    current = local.timetz().replace(tzinfo=None)
    if start_value < end_value:
        in_quiet = start_value <= current < end_value
        end_date = local.date()
    else:
        in_quiet = current >= start_value or current < end_value
        end_date = local.date() + (
            timedelta(days=1) if current >= start_value else timedelta()
        )
    if not in_quiet:
        return now
    next_local = datetime.combine(end_date, end_value, tzinfo=zone)
    return next_local.astimezone(UTC)


__all__ = [
    "ReminderConflictError",
    "ReminderError",
    "ReminderNotFoundError",
    "build_next_action_agenda",
    "deliver_due_reminders",
    "dismiss_reminder",
    "list_reminder_inbox",
    "notification_preference",
    "update_notification_preference",
]
