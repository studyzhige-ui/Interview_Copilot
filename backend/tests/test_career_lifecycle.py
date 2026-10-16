"""Confirmed profile writes and reminders preserve ownership and user intent."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.career.application import process, profile, reminders
from app.core.security import get_current_user
from app.db.database import get_db
from app.main import app
from app.schemas.career_insights import NotificationPreferenceUpdate
from app.schemas.career_profile import ConfirmationInput, SkillFactInput
from app.schemas.job_opportunity import NextActionCreate


def test_profile_edits_return_new_version_and_reject_stale_or_foreign_ids(db, owners):
    owner, other = owners
    initial = profile.ensure_career_profile(db, user_pk=owner.id)
    version = initial.version
    command = dict(
        user_pk=owner.id,
        expected_profile_version=version,
        fact=SkillFactInput(kind="skill", name="Python"),
        confirmation=ConfirmationInput(kind="user_edit"),
    )
    result = profile.upsert_personal_fact(db, **command)
    assert result.version == version + 1
    fact_id = result.personal_facts[0].id
    with pytest.raises(profile.CareerProfileConflictError):
        profile.upsert_personal_fact(db, **command)
    other_profile = profile.ensure_career_profile(db, user_pk=other.id)
    with pytest.raises(profile.CareerProfileNotFoundError):
        profile.upsert_personal_fact(
            db,
            **{
                **command,
                "user_pk": other.id,
                "expected_profile_version": other_profile.version,
            },
            fact_id=fact_id,
        )
    removed = profile.remove_personal_fact(
        db,
        user_pk=owner.id,
        expected_profile_version=result.version,
        fact_id=fact_id,
        confirmation=command["confirmation"],
    )
    assert not removed.personal_facts and removed.version == result.version + 1


@pytest.mark.parametrize("timezone", ["/etc/passwd", "../UTC", "Unknown/Zone"])
def test_invalid_notification_timezone_is_a_client_error(db, owners, timezone):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: owners[0]
    try:
        client = TestClient(app, raise_server_exceptions=False)
        response = client.put(
            "/api/v1/career-insights/notification-preference",
            json={"expected_version": 0, "timezone": timezone},
        )
        assert response.status_code == 422, response.text
    finally:
        app.dependency_overrides.clear()


def test_reminders_defer_until_quiet_hours_end_deliver_once_and_stay_owned(db, owners):
    owner, other = owners
    now = datetime(2030, 1, 1, 15, tzinfo=UTC)  # 23:00 in Shanghai
    preference = reminders.update_notification_preference(
        db,
        user_pk=owner.id,
        command=NotificationPreferenceUpdate(
            expected_version=0,
            timezone="Asia/Shanghai",
            quiet_start="22:00",
            quiet_end="08:00",
        ),
    )
    action = process.create_next_action(
        db,
        user_pk=owner.id,
        command=NextActionCreate(
            content="Review interview notes",
            status="planned",
            time_kind="flexible",
            source_kind="user_request",
            source_identity="test",
            reminder_at=now,
            reminder_channel="in_app",
        ),
    )
    assert reminders.deliver_due_reminders(db, due_at=now)["deferred_quiet"] == 1
    next_morning = now + timedelta(hours=9)
    assert action.reminder_next_attempt_at == next_morning
    assert reminders.deliver_due_reminders(db, due_at=next_morning)["delivered"] == 1
    assert reminders.deliver_due_reminders(db, due_at=next_morning)["delivered"] == 0
    assert not reminders.list_reminder_inbox(db, user_pk=other.id)
    with pytest.raises(reminders.ReminderNotFoundError):
        reminders.dismiss_reminder(
            db, user_pk=other.id, action_id=action.id, expected_version=action.version
        )
    reminders.dismiss_reminder(
        db, user_pk=owner.id, action_id=action.id, expected_version=action.version
    )
    assert not reminders.list_reminder_inbox(db, user_pk=owner.id)
    assert action.status == "planned" and preference.enabled
