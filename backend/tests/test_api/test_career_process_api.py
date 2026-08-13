from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import career_process
from app.core.security import get_current_user
from app.db.database import get_db
from app.models.career_profile import CareerProfile, CareerProfileDirection
from app.models.job_opportunity import JobOpportunity, ProcessEvent
from app.models.user import User


NOW = datetime(2026, 8, 13, 9, 0, tzinfo=UTC)


@pytest.fixture
def career_api(db_session):
    owner = User(username="career-api-owner", hashed_password="x")
    other = User(username="career-api-other", hashed_password="x")
    db_session.add_all([owner, other])
    db_session.commit()
    principal = {"user": owner}

    async def current_user():
        return principal["user"]

    def current_db():
        yield db_session

    app = FastAPI()
    app.include_router(career_process.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = current_user
    app.dependency_overrides[get_db] = current_db
    return TestClient(app), principal, owner, other


def _opportunity_payload(**overrides):
    values = {
        "company_name": "Example Corp",
        "job_title": "Backend Engineer",
        "entry_reason": "explicit_tracking",
        "occurred_at": NOW.isoformat(),
        "source_kind": "user_assertion",
        "source_identity": "request-create-1",
        "source_description": "用户明确要求跟踪这个岗位",
        "source_url": "https://jobs.example.com/roles/42#details",
        "source_provider": "example",
        "external_job_id": "job-42",
        "idempotency_key": "opportunity-create-1",
    }
    values.update(overrides)
    return values


def _event_payload(kind: str, **overrides):
    values = {
        "kind": kind,
        "occurred_at": (NOW + timedelta(days=1)).isoformat(),
        "source_kind": "user_assertion",
        "source_identity": f"request-{kind}",
        "description": f"用户确认 {kind}",
        "idempotency_key": f"event-{kind}",
    }
    values.update(overrides)
    return values


def _create_opportunity(client: TestClient, **overrides) -> dict:
    response = client.post(
        "/api/v1/career-process/opportunities",
        json=_opportunity_payload(**overrides),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _direction(db_session, user: User, label: str) -> CareerProfileDirection:
    profile = CareerProfile(user_id=user.id, personal_facts_json=[])
    db_session.add(profile)
    db_session.flush()
    direction = CareerProfileDirection(
        career_profile_id=profile.id,
        label=label,
        criteria_json={},
        lifecycle="active",
        priority=0,
        confirmed_source_kind="user_edit",
        confirmed_at=NOW,
    )
    db_session.add(direction)
    db_session.commit()
    return direction


def test_opportunity_create_list_idempotency_and_owner_scope(career_api):
    client, principal, owner, other = career_api

    created = _create_opportunity(client)
    retried = client.post(
        "/api/v1/career-process/opportunities",
        json=_opportunity_payload(),
    )

    assert retried.status_code == 200
    assert retried.json()["id"] == created["id"]
    assert client.get("/api/v1/career-process/opportunities").json() == [created]

    conflict_payload = _opportunity_payload(job_title="Different Role")
    conflict = client.post(
        "/api/v1/career-process/opportunities",
        json=conflict_payload,
    )
    assert conflict.status_code == 409

    principal["user"] = other
    assert client.get("/api/v1/career-process/opportunities").json() == []
    hidden_timeline = client.get(
        f"/api/v1/career-process/opportunities/{created['id']}/events"
    )
    assert hidden_timeline.status_code == 404

    principal["user"] = owner
    timeline = client.get(
        f"/api/v1/career-process/opportunities/{created['id']}/events"
    )
    assert timeline.status_code == 200
    assert [row["kind"] for row in timeline.json()] == ["tracking_started"]


def test_opportunity_direction_create_read_and_cas_update(career_api, db_session):
    client, principal, owner, other = career_api
    backend = _direction(db_session, owner, "Backend")
    foreign = _direction(db_session, other, "Foreign")
    created = _create_opportunity(
        client,
        directions=[
            {"direction_id": backend.id, "match_reason": "岗位职责匹配"},
        ],
    )

    assert created["direction_version"] == 1
    assert created["direction_links"][0]["career_profile_direction_id"] == backend.id
    assert (
        client.get("/api/v1/career-process/opportunities").json()[0]["direction_links"][
            0
        ]["match_reason"]
        == "岗位职责匹配"
    )

    endpoint = f"/api/v1/career-process/opportunities/{created['id']}/directions"
    updated = client.patch(
        endpoint,
        json={
            "expected_version": 1,
            "directions": [],
            "source_kind": "user_assertion",
            "source_identity": "request-unlink",
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["direction_version"] == 2
    assert updated.json()["direction_links"] == []

    stale = client.patch(
        endpoint,
        json={
            "expected_version": 1,
            "directions": [],
            "source_kind": "user_assertion",
            "source_identity": "request-stale",
        },
    )
    assert stale.status_code == 409

    cross_owner = client.patch(
        endpoint,
        json={
            "expected_version": 2,
            "directions": [
                {"direction_id": foreign.id, "match_reason": "must stay hidden"},
            ],
            "source_kind": "user_assertion",
            "source_identity": "request-cross-owner",
        },
    )
    assert cross_owner.status_code == 404

    principal["user"] = other
    hidden = client.patch(
        endpoint,
        json={
            "expected_version": 2,
            "directions": [],
            "source_kind": "user_assertion",
            "source_identity": "request-hidden-opportunity",
        },
    )
    assert hidden.status_code == 404


def test_append_and_correct_are_append_only_and_idempotent(career_api):
    client, _principal, _owner, _other = career_api
    opportunity = _create_opportunity(client)
    events_url = f"/api/v1/career-process/opportunities/{opportunity['id']}/events"
    append_payload = _event_payload(
        "interview_scheduled",
        step_summary="已约一面",
    )

    appended = client.post(events_url, json=append_payload)
    retried = client.post(events_url, json=append_payload)

    assert appended.status_code == 201
    assert retried.status_code == 201
    assert retried.json()["id"] == appended.json()["id"]

    conflicting_retry = client.post(
        events_url,
        json={**append_payload, "description": "同一 key 的不同事实"},
    )
    assert conflicting_retry.status_code == 409

    correction = client.post(
        f"{events_url}/{appended.json()['id']}/corrections",
        json={
            "replacement_kind": "application_acknowledged",
            "occurred_at": (NOW + timedelta(days=2)).isoformat(),
            "source_kind": "user_assertion",
            "source_identity": "request-correct-interview",
            "description": "用户澄清这只是申请收件确认",
            "idempotency_key": "correction-1",
        },
    )

    assert correction.status_code == 201
    assert correction.json()["corrects_event_id"] == appended.json()["id"]
    timeline = client.get(events_url).json()
    assert [row["sequence"] for row in timeline] == [1, 2, 3]
    assert timeline[1]["kind"] == "interview_scheduled"
    assert timeline[2]["kind"] == "application_acknowledged"


def test_public_event_api_rejects_unverified_external_sources(career_api, db_session):
    client, _principal, owner, _other = career_api

    observation_admission = client.post(
        "/api/v1/career-process/opportunities",
        json=_opportunity_payload(
            source_kind="observation",
            source_identity="unverified-email-candidate",
        ),
    )
    verified_without_receipt = client.post(
        "/api/v1/career-process/opportunities",
        json=_opportunity_payload(
            entry_reason="verified_submission",
            source_identity="request-claims-verification",
        ),
    )

    assert observation_admission.status_code == 422
    assert verified_without_receipt.status_code == 422
    assert (
        db_session.query(JobOpportunity)
        .filter(JobOpportunity.user_id == owner.id)
        .count()
        == 0
    )

    opportunity = _create_opportunity(client)
    events_url = f"/api/v1/career-process/opportunities/{opportunity['id']}/events"
    for source_kind in ("observation", "tool_result", "provider_receipt"):
        response = client.post(
            events_url,
            json=_event_payload(
                "recruiter_contact",
                source_kind=source_kind,
                source_identity=f"forged-{source_kind}",
                idempotency_key=f"forged-{source_kind}",
            ),
        )
        assert response.status_code == 422

    assert db_session.query(ProcessEvent).count() == 1


def test_next_action_routes_use_real_process_events_and_four_state_lifecycle(
    career_api,
):
    client, _principal, _owner, _other = career_api
    opportunity = _create_opportunity(
        client,
        entry_reason="user_confirmed_application",
        source_identity="request-confirmed-application",
    )
    events_url = f"/api/v1/career-process/opportunities/{opportunity['id']}/events"
    invited = client.post(
        events_url,
        json=_event_payload(
            "assessment_invited",
            step_summary="技术测评周五截止",
        ),
    ).json()

    suggested = client.post(
        "/api/v1/career-process/next-actions",
        json={
            "content": "完成技术测评",
            "status": "suggested",
            "time_kind": "deadline",
            "due_at": (NOW + timedelta(days=5)).isoformat(),
            "original_time_text": "本周五 18:00 前",
            "source_timezone": "Asia/Shanghai",
            "source_kind": "process_event",
            "source_identity": invited["id"],
            "idempotency_key": "action-assessment",
        },
    )
    assert suggested.status_code == 201, suggested.text
    action_id = suggested.json()["id"]
    assert suggested.json()["job_opportunity_id"] == opportunity["id"]

    planned = client.post(
        f"/api/v1/career-process/next-actions/{action_id}/plan",
        json={
            "source_kind": "user_assertion",
            "source_identity": "request-plan-assessment",
        },
    )
    assert planned.status_code == 200
    assert planned.json()["status"] == "planned"

    completed_event = client.post(
        events_url,
        json=_event_payload(
            "assessment_completed",
            occurred_at=(NOW + timedelta(days=3)).isoformat(),
        ),
    ).json()
    completed = client.post(
        f"/api/v1/career-process/next-actions/{action_id}/complete",
        json={
            "source_kind": "process_event",
            "source_identity": completed_event["id"],
        },
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "done"
    assert completed.json()["resolution_source_identity"] == completed_event["id"]

    done_actions = client.get(
        "/api/v1/career-process/next-actions",
        params=[("statuses", "done")],
    )
    assert [row["id"] for row in done_actions.json()] == [action_id]

    planned_directly = client.post(
        "/api/v1/career-process/next-actions",
        json={
            "content": "整理岗位问题",
            "status": "planned",
            "time_kind": "flexible",
            "source_kind": "user_request",
            "source_identity": "request-create-plan",
            "idempotency_key": "action-plan-directly",
        },
    ).json()
    closed = client.post(
        f"/api/v1/career-process/next-actions/{planned_directly['id']}/close",
        json={
            "source_kind": "user_assertion",
            "source_identity": "request-close-plan",
            "reason": "岗位要求已经变化，不再需要",
        },
    )
    assert closed.status_code == 200
    assert closed.json()["status"] == "closed"
    assert closed.json()["close_reason"] == "岗位要求已经变化，不再需要"


def test_next_action_api_rejects_fake_runtime_and_cross_owner_sources(career_api):
    client, principal, owner, other = career_api
    opportunity = _create_opportunity(client)
    event = client.get(
        f"/api/v1/career-process/opportunities/{opportunity['id']}/events"
    ).json()[0]

    fake_agent_suggestion = client.post(
        "/api/v1/career-process/next-actions",
        json={
            "content": "模型建议",
            "status": "suggested",
            "time_kind": "flexible",
            "source_kind": "agent_suggestion",
            "source_identity": "turn-that-was-not-validated",
        },
    )
    fake_agent_task = client.post(
        "/api/v1/career-process/next-actions",
        json={
            "content": "复用 AgentTask",
            "status": "suggested",
            "time_kind": "flexible",
            "source_kind": "agent_task",
            "source_identity": "agent-task-1",
        },
    )
    assert fake_agent_suggestion.status_code == 422
    assert fake_agent_task.status_code == 422

    direct_plan = client.post(
        "/api/v1/career-process/next-actions",
        json={
            "content": "整理岗位问题",
            "status": "planned",
            "time_kind": "flexible",
            "source_kind": "user_request",
            "source_identity": "request-real-plan",
        },
    ).json()
    forged_tool_result = client.post(
        f"/api/v1/career-process/next-actions/{direct_plan['id']}/complete",
        json={
            "source_kind": "tool_result",
            "source_identity": "tool-call-that-was-not-validated",
        },
    )
    assert forged_tool_result.status_code == 422

    principal["user"] = other
    cross_owner_event = client.post(
        "/api/v1/career-process/next-actions",
        json={
            "content": "跨用户事件动作",
            "status": "suggested",
            "time_kind": "flexible",
            "source_kind": "process_event",
            "source_identity": event["id"],
        },
    )
    assert cross_owner_event.status_code == 404

    principal["user"] = owner
    assert [
        row["id"] for row in client.get("/api/v1/career-process/next-actions").json()
    ] == [direct_plan["id"]]


def test_archived_opportunity_rejects_ordinary_updates_and_new_actions(career_api):
    client, _principal, _owner, _other = career_api
    opportunity = _create_opportunity(client)
    events_url = f"/api/v1/career-process/opportunities/{opportunity['id']}/events"
    terminal = client.post(events_url, json=_event_payload("rejected"))
    assert terminal.status_code == 201

    late_update = client.post(
        events_url,
        json=_event_payload(
            "recruiter_contact",
            source_identity="late-message",
            idempotency_key="late-event",
        ),
    )
    new_action = client.post(
        "/api/v1/career-process/next-actions",
        json={
            "content": "继续跟进已封存岗位",
            "status": "planned",
            "time_kind": "flexible",
            "source_kind": "user_request",
            "source_identity": "request-late-action",
            "job_opportunity_id": opportunity["id"],
        },
    )
    assert late_update.status_code == 409
    assert new_action.status_code == 409
    assert client.get("/api/v1/career-process/opportunities").json() == []
    archived = client.get(
        "/api/v1/career-process/opportunities",
        params={"include_archived": "true"},
    )
    assert [row["id"] for row in archived.json()] == [opportunity["id"]]
