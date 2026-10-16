"""Home prioritizes unfinished work and owned upcoming interview schedules."""

import uuid
from datetime import timedelta

from app.api.workspace import overview
from app.db.types import utc_now
from app.models.chat import Conversation
from app.models.conversation_turn import ConversationTurn
from app.career.application.interview_invitation_operations import (
    confirm_interview_invitation,
)
from app.schemas.interview_invitation import ConfirmInterviewInvitation


def test_home_filters_before_limiting_and_uses_only_the_latest_turn(db, owners):
    owner, other = owners
    expected = set()
    for index, (user, statuses) in enumerate(
        [
            (owner, ["waiting"]),
            (owner, ["running"]),
            (owner, ["failed", "completed"]),
            (owner, ["completed"]),
            (owner, ["cancelled"]),
            (owner, []),
            (other, ["waiting"]),
        ]
    ):
        identity = str(uuid.uuid4())
        db.add(
            Conversation(
                id=identity,
                user_id=user.id,
                type="general",
                updated_at=utc_now() + timedelta(seconds=index),
            )
        )
        db.flush()
        for number, status in enumerate(statuses):
            db.add(
                ConversationTurn(
                    conversation_id=identity,
                    user_id=user.id,
                    mode="chat",
                    message="synthetic",
                    status=status,
                    created_at=utc_now() + timedelta(seconds=number),
                )
            )
        if user is owner and statuses and statuses[-1] in {"waiting", "running"}:
            expected.add(identity)
    db.flush()
    result = overview(current_user=owner, db=db)
    assert {row.session_id for row in result.recent_work} == expected
    assert {row.status for row in result.recent_work} == {"waiting", "running"}


def test_home_interview_schedule_is_owned_future_bounded_and_read_only(
    db, owners, monkeypatch
):
    owner, other = owners
    expected = []
    for user, days in [(owner, 1), (owner, -1), (owner, 31), (other, 2)]:
        identity = str(uuid.uuid4())
        result = confirm_interview_invitation(
            db,
            user_pk=user.id,
            command=ConfirmInterviewInvitation.model_validate(
                {
                    "idempotency_key": identity,
                    "actor_kind": "user",
                    "asserted_at": utc_now(),
                    "confirmation_basis": {
                        "kind": "explicit_user_assertion",
                        "source": {"kind": "manual", "identity": identity},
                    },
                    "facts": {
                        "company_name": "Synthetic company",
                        "job_title": "Engineer",
                        "scheduled_start_at": utc_now() + timedelta(days=days),
                        "original_time_text": "synthetic schedule",
                        "source_timezone": "Asia/Shanghai",
                        "location": "Test location",
                        "meeting_url": "https://example.com/test-meeting",
                        "contact_name": "Test contact",
                    },
                    "opportunity": {"kind": "create_new"},
                }
            ),
        )
        if user is owner and days == 1:
            expected.append(result.interview.id)
            expected_job = result.opportunity.id
    db.flush()
    result = overview(current_user=owner, db=db)
    assert [row.id for row in result.upcoming_interviews] == expected
    assert result.open_actions == 0  # A schedule is not silently turned into a task.
    import importlib
    from app.api.interviews.records import list_interview_records

    module = importlib.import_module(
        "app.interviews.application.interview_record_service"
    )
    monkeypatch.setattr(module, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    rows = list_interview_records(
        current_user=owner, offset=0, limit=20, job_opportunity_id=expected_job
    )
    assert [row.id for row in rows] == expected
    assert rows[0].scheduled_location == "Test location"
    assert rows[0].meeting_url == "https://example.com/test-meeting"
    assert rows[0].contact == {"name": "Test contact"}
    assert (
        list_interview_records(
            current_user=other, offset=0, limit=20, job_opportunity_id=expected_job
        )
        == []
    )
    assert (
        list_interview_records(
            current_user=owner,
            offset=0,
            limit=20,
            job_opportunity_id=None,
            include_invitations=False,
        )
        == []
    )


def test_retired_preparation_page_does_not_advertise_api_or_agent_actions():
    from app.main import app as application
    import app.agent_runtime.tools  # noqa: F401
    from app.agent_runtime.tool_registry import registry

    paths = application.openapi()["paths"]
    assert "/api/v1/career/interview-invitations/interviews" not in paths
    assert (
        "/api/v1/career/interview-invitations/interviews/{interview_id}/handoff"
        not in paths
    )
    assert registry.get("open_interview_preparation") is None
    assert "/api/v1/career/interview-invitations/confirm" in paths
    assert registry.get("confirm_interview_invitation") is not None
