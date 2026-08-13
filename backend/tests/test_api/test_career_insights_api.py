from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import career_insights
from app.core.security import get_current_user
from app.db.database import get_db
from app.models.job_opportunity import JobOpportunity, NextAction
from app.models.offer import Offer
from app.models.user import User


@pytest.fixture
def insights_api(db_session):
    owner = User(username="insights-api-owner", hashed_password="x")
    other = User(username="insights-api-other", hashed_password="x")
    db_session.add_all([owner, other])
    db_session.commit()

    async def current_user():
        return owner

    def current_db():
        yield db_session

    app = FastAPI()
    app.include_router(career_insights.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = current_user
    app.dependency_overrides[get_db] = current_db
    return TestClient(app), owner, other


def test_notification_preference_and_agenda_contract(insights_api, db_session):
    client, owner, _other = insights_api
    default = client.get("/api/v1/career-insights/notification-preference")
    assert default.status_code == 200
    assert default.json()["version"] == 0

    updated = client.put(
        "/api/v1/career-insights/notification-preference",
        json={
            "expected_version": 0,
            "enabled": True,
            "default_channel": "in_app",
            "timezone": "Asia/Shanghai",
            "quiet_start": "22:00",
            "quiet_end": "08:00",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 1
    assert (
        client.put(
            "/api/v1/career-insights/notification-preference",
            json={
                "expected_version": 0,
                "enabled": False,
                "default_channel": "in_app",
                "timezone": "UTC",
            },
        ).status_code
        == 409
    )

    now = datetime.now(UTC)
    action = NextAction(
        user_id=owner.id,
        content="完成作业",
        status="planned",
        time_kind="deadline",
        due_at=now + timedelta(hours=2),
        original_time_text="两小时后",
        source_timezone="UTC",
        source_kind="user_request",
        source_identity="ui:agenda",
        planned_at=now,
        planned_source_kind="user_assertion",
        planned_source_identity="ui:agenda",
    )
    db_session.add(action)
    db_session.commit()
    agenda = client.get("/api/v1/career-insights/next-actions/agenda")
    assert agenda.status_code == 200
    assert agenda.json()["items"][0]["action"]["id"] == action.id
    assert agenda.json()["items"][0]["due_soon"] is True


def test_offer_analysis_fails_closed_for_another_user(insights_api, db_session):
    client, _owner, other = insights_api
    job = JobOpportunity(
        user_id=other.id,
        company_name="Private Co",
        job_title="Engineer",
        phase="offer",
        current_step="Offer",
    )
    db_session.add(job)
    db_session.flush()
    offer = Offer(
        user_id=other.id,
        job_opportunity_id=job.id,
        terms_json={},
        term_sources_json={},
        source_excerpts_json={},
        creation_operation_key="foreign",
        creation_operation_fingerprint="a" * 64,
        last_operation_key="foreign",
        last_operation_fingerprint="a" * 64,
        last_source_kind="user_assertion",
        last_source_identity="1",
        last_source_observed_at=datetime.now(UTC),
    )
    db_session.add(offer)
    db_session.commit()
    response = client.post(
        "/api/v1/career-insights/offers/compare",
        json={"offer_ids": [offer.id], "base_currency": "CNY"},
    )
    assert response.status_code == 404
