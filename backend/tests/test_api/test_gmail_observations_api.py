from __future__ import annotations

from datetime import UTC, datetime
from typing import Iterator

import app.models  # noqa: F401
import pytest
from app.api import gmail_observations, persistent_tasks
from app.core.security import get_current_user
from app.db.database import Base, get_db
from app.models.gmail_integration import GmailIntegrationAccount
from app.models.gmail_observation import GmailObservation
from app.models.job_opportunity import JobOpportunity, ProcessEvent
from app.models.persistent_task import PersistentTaskTrigger
from app.models.user import User
from app.schemas.gmail_observation import (
    GmailIncrementalBatch,
    GmailIncrementalMessage,
    GmailObservationProposal,
)
from app.services import gmail_observation_service, gmail_observation_sync_service
from app.services.gmail_integration_service import (
    GMAIL_READONLY_SCOPE,
    GmailGrantInspection,
    GmailProviderAdapterError,
    bind_verified_grant,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


NOW = datetime(2026, 8, 13, 8, 0, tzinfo=UTC)


class FakeHistoryAdapter:
    message_count = 1
    failure_code: str | None = None

    async def inspect_grant(self, _handle: str, *, user_pk: int):
        assert user_pk > 0
        return GmailGrantInspection(
            google_subject="google-subject",
            account_email="alice@gmail.com",
            granted_scopes=frozenset({GMAIL_READONLY_SCOPE}),
        )

    async def read_incremental_messages(
        self, _handle: str, *, user_pk: int, cursor: str | None, limit: int
    ) -> GmailIncrementalBatch:
        assert user_pk > 0 and limit <= 100
        if self.failure_code is not None:
            raise GmailProviderAdapterError(self.failure_code)
        if cursor is None:
            return GmailIncrementalBatch(
                cursor_after="100", initialized_cursor=True, messages=[]
            )
        return GmailIncrementalBatch(
            cursor_before=cursor,
            cursor_after="101",
            messages=[
                GmailIncrementalMessage(
                    message_id=f"msg-{index}",
                    thread_id=f"thread-{index}",
                    history_id=str(100 + index),
                    received_at=NOW,
                    from_hint="recruiter@example.com",
                    subject=f"Interview invitation {index}",
                    snippet="Please pick a time.",
                )
                for index in range(1, self.message_count + 1)
            ],
        )

    async def search_messages(self, *_args, **_kwargs):
        return []

    async def revoke_grant(self, *_args, **_kwargs):
        return None


@pytest.fixture
def db() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def api_context(db: Session, monkeypatch):
    user = User(username="gmail-observation-api", hashed_password="x")
    db.add(user)
    db.commit()
    adapter = FakeHistoryAdapter()
    import asyncio

    asyncio.run(
        bind_verified_grant(
            db,
            user_pk=user.id,
            credential_handle="gch_abcdefghijklmnopqrstuvwx",
            adapter=adapter,
        )
    )
    db.commit()

    def fake_db() -> Iterator[Session]:
        yield db

    app = FastAPI()
    app.include_router(persistent_tasks.router, prefix="/api/v1")
    app.include_router(gmail_observations.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[gmail_observations.get_gmail_provider_adapter] = lambda: (
        adapter
    )
    dispatched: list[str] = []
    monkeypatch.setattr(
        gmail_observation_sync_service,
        "dispatch_sync_admissions",
        lambda result: (
            dispatched.extend(result.admitted_turn_ids) or len(result.admitted_turn_ids)
        ),
    )
    with TestClient(app) as client:
        yield client, db, user, dispatched, adapter


def _event_task(client: TestClient) -> dict:
    response = client.post(
        "/api/v1/persistent-tasks",
        json={
            "title": "Gmail 求职事件",
            "instruction": "处理新增的求职邮件，模糊内容先让我确认。",
            "trigger": {
                "kind": "event",
                "connector": "gmail",
                "event_types": ["message_added"],
            },
            "read_scope": ["gmail:job_observations"],
            "action_scope": [],
            "allowed_tool_names": [
                "read_career_context",
                "read_gmail_observations",
                "review_gmail_observation",
            ],
            "user_request_identity": "message:create",
            "idempotency_key": "gmail-event-task",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _job(db: Session, user: User) -> JobOpportunity:
    job = JobOpportunity(
        user_id=user.id,
        company_name="Example",
        job_title="Engineer",
        phase="applied",
        current_step="已确认投递",
    )
    db.add(job)
    db.flush()
    db.add(
        ProcessEvent(
            job_opportunity_id=job.id,
            sequence=1,
            operation="assert",
            kind="application_submitted",
            occurred_at=NOW,
            observed_at=NOW,
            source_kind="user_assertion",
            source_identity="message:application",
            description="用户确认投递",
            idempotency_key="initial",
        )
    )
    db.commit()
    return job


def test_sync_creates_observation_event_trigger_and_dedicated_turn(api_context):
    client, db, _user, dispatched, _adapter = api_context
    task = _event_task(client)

    initialized = client.post("/api/v1/gmail/observations/sync")
    assert initialized.status_code == 202, initialized.text
    assert initialized.json()["initialized_cursor"] is True

    synced = client.post("/api/v1/gmail/observations/sync")
    assert synced.status_code == 202, synced.text
    payload = synced.json()
    assert payload["observations_created"] == 1
    assert payload["triggers_created"] == 1
    assert payload["turns_admitted"] == 1
    assert dispatched == payload["turn_ids"]
    observation = client.get("/api/v1/gmail/observations").json()[0]
    assert observation["latest_snapshot"]["subject"] == "Interview invitation 1"
    trigger = db.query(PersistentTaskTrigger).one()
    assert trigger.source_identity == observation["id"]
    assert trigger.persistent_task_id == task["id"]
    assert trigger.admitted_turn_id == payload["turn_ids"][0]


def test_review_card_api_approves_then_observation_api_retracts(api_context):
    client, db, user, _dispatched, _adapter = api_context
    task = _event_task(client)
    client.post("/api/v1/gmail/observations/sync")
    synced = client.post("/api/v1/gmail/observations/sync").json()
    observation = db.query(GmailObservation).one()
    job = _job(db, user)

    gmail_observation_service.propose_observation(
        db,
        user_pk=user.id,
        task_id=task["id"],
        automation_turn_id=synced["turn_ids"][0],
        proposal=GmailObservationProposal(
            observation_id=observation.id,
            expected_version=1,
            disposition="needs_confirmation",
            event_kind="interview_scheduled",
            opportunity_id=job.id,
            occurred_at=NOW,
            description="面试邀请",
            confidence=0.8,
            unique_match=True,
            rationale="需要用户确认具体安排。",
        ),
    )
    db.commit()

    cards = client.get(
        f"/api/v1/persistent-tasks/{task['id']}/gmail-review-cards",
        params={"statuses": "pending"},
    )
    assert cards.status_code == 200, cards.text
    card = cards.json()[0]
    approved = client.post(
        f"/api/v1/persistent-tasks/{task['id']}/gmail-review-cards/{card['id']}/resolve",
        json={
            "expected_version": card["version"],
            "decision": "approve",
            "user_request_identity": "product_ui:approve",
        },
    )
    assert approved.status_code == 200, approved.text
    applied = approved.json()["observation"]
    assert applied["status"] == "applied"

    retracted = client.post(
        f"/api/v1/gmail/observations/{observation.id}/retract",
        json={
            "expected_version": applied["version"],
            "occurred_at": NOW.isoformat(),
            "reason": "用户确认匹配错误",
            "user_request_identity": "product_ui:retract",
        },
    )
    assert retracted.status_code == 200, retracted.text
    assert retracted.json()["status"] == "retracted"
    assert (
        db.query(ProcessEvent).filter(ProcessEvent.job_opportunity_id == job.id).count()
        == 3
    )


def test_one_provider_batch_merges_all_observation_triggers_into_one_turn(
    api_context,
):
    client, db, _user, dispatched, adapter = api_context
    _event_task(client)
    initialized = client.post("/api/v1/gmail/observations/sync")
    assert initialized.status_code == 202
    adapter.message_count = 2

    synced = client.post("/api/v1/gmail/observations/sync")
    assert synced.status_code == 202, synced.text
    payload = synced.json()
    assert payload["observations_created"] == 2
    assert payload["triggers_created"] == 2
    assert payload["turns_admitted"] == 1
    triggers = db.query(PersistentTaskTrigger).order_by(PersistentTaskTrigger.id).all()
    assert len(triggers) == 2
    assert {trigger.admitted_turn_id for trigger in triggers} == {
        payload["turn_ids"][0]
    }
    assert dispatched == payload["turn_ids"]


def test_sync_failure_persists_safe_reconnect_state_after_atomic_rollback(
    api_context,
):
    client, db, _user, _dispatched, adapter = api_context
    _event_task(client)
    adapter.failure_code = "invalid_grant"

    failed = client.post("/api/v1/gmail/observations/sync")
    assert failed.status_code == 409
    assert failed.json()["detail"] == "gmail_connection_required"
    db.expire_all()
    account = db.query(GmailIntegrationAccount).one()
    assert account.status == "invalid"
    assert account.last_error_code == "invalid_grant"
    assert account.last_observation_sync_error_code == "invalid_grant"


def test_expired_cursor_requires_explicit_rebaseline_and_clears_error(api_context):
    client, db, _user, _dispatched, adapter = api_context
    _event_task(client)
    initialized = client.post("/api/v1/gmail/observations/sync")
    assert initialized.status_code == 202
    adapter.failure_code = "history_cursor_expired"

    failed = client.post("/api/v1/gmail/observations/sync")
    assert failed.status_code == 409
    assert failed.json()["detail"] == "history_cursor_expired"
    db.expire_all()
    account = db.query(GmailIntegrationAccount).one()
    assert account.status == "active"
    assert account.history_cursor == "100"
    assert account.last_observation_sync_error_code == "history_cursor_expired"

    adapter.failure_code = None
    recovered = client.post(
        "/api/v1/gmail/observations/rebaseline",
        json={
            "confirm_gap": True,
            "user_request_identity": "product_ui:rebaseline",
        },
    )
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["initialized_cursor"] is True
    db.expire_all()
    account = db.query(GmailIntegrationAccount).one()
    assert account.history_cursor == "100"
    assert account.last_observation_sync_error_code is None
