"""HTTP contract tests for explicit Artifact and single-current Offer routes."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# Register these independent Stage slices before Base.metadata.create_all.
from app.api import artifacts as artifacts_api
from app.api import offers as offers_api
from app.core.security import get_current_user
from app.db.database import Base, get_db
from app.models.agent_execution import AgentToolCall
from app.models.artifact import ArtifactSubmissionSnapshot
from app.models.chat import Conversation, ConversationMessage
from app.models.conversation_turn import ConversationTurn
from app.models.file_asset import FileAsset
from app.models.job_opportunity import JobOpportunity
from app.models.offer import Offer
from app.models.user import User
from app.schemas.artifact import ArtifactWriteInput
from app.services import artifact_service

NOW = datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc)


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
def alice(db: Session) -> User:
    row = User(
        username="alice",
        email="alice@example.com",
        hashed_password="x",
    )
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def client(db: Session, alice: User) -> Iterator[TestClient]:
    def fake_user() -> User:
        return alice

    def fake_db() -> Iterator[Session]:
        yield db

    app = FastAPI()
    app.include_router(artifacts_api.router, prefix="/api/v1")
    app.include_router(offers_api.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = fake_user
    app.dependency_overrides[get_db] = fake_db
    yield TestClient(app)


def _job(db: Session, user: User, suffix: str = "1") -> JobOpportunity:
    row = JobOpportunity(
        id=f"jo_{suffix.zfill(32)}",
        user_id=user.id,
        company_name="Example Co",
        job_title="Backend Engineer",
        phase="offer",
        current_step="已收到 Offer",
    )
    db.add(row)
    db.commit()
    return row


def _message(
    db: Session,
    user: User,
    *,
    role: str,
    content: str,
    conversation_id: str,
) -> ConversationMessage:
    conversation = Conversation(
        id=conversation_id,
        user_id=user.id,
        title="source",
        type="general",
    )
    db.add(conversation)
    db.flush()
    row = ConversationMessage(
        conversation_id=conversation.id,
        seq=1,
        role=role,
        content=content,
    )
    db.add(row)
    db.commit()
    return row


def _asset(db: Session, user: User, asset_id: str) -> FileAsset:
    row = FileAsset(
        id=asset_id,
        user_id=user.id,
        purpose="agent_output",
        original_filename="offer.pdf",
        object_key=f"uploads/{user.id}/{asset_id}/offer.pdf",
        storage_uri=f"s3://bucket/uploads/{user.id}/{asset_id}/offer.pdf",
        content_type="application/pdf",
        size_bytes=100,
        checksum_sha256="a" * 64,
        upload_status="uploaded",
        validation_status="passed",
    )
    db.add(row)
    db.commit()
    return row


def _offer_terms(salary: str) -> dict:
    return {
        "position_title": "Backend Engineer",
        "base_salary_amount": salary,
        "currency": "CNY",
        "pay_period": "annual",
        "tax_basis": "gross",
        "formality": "written",
        "original_text": f"Annual gross base salary CNY {salary}.",
    }


def _source(kind: str, identity: str, version: str | None = None) -> dict:
    result = {
        "kind": kind,
        "identity": identity,
        "observed_at": NOW.isoformat(),
    }
    if version is not None:
        result["version"] = version
    return result


def test_artifact_http_requires_explicit_save_or_message_promotion(
    client: TestClient,
    db: Session,
    alice: User,
):
    assistant = _message(
        db,
        alice,
        role="Assistant",
        content="A normal answer is still only conversation history.",
        conversation_id="artifact-conv",
    )
    assert db.query(ArtifactSubmissionSnapshot).count() == 0

    saved = client.post(
        "/api/v1/artifacts",
        json={
            "operation_key": "save-report-1",
            "artifact_kind": "report",
            "version": {"title": "Saved report", "content_text": "body"},
        },
    )
    assert saved.status_code == 201, saved.text
    assert saved.json()["current_version"]["origin_kind"] == "explicit_save"

    promoted = client.post(
        "/api/v1/artifacts/from-message",
        json={
            "operation_key": "promote-message-1",
            "artifact_kind": "report",
            "title": "Conversation report",
            "source_message_id": assistant.id,
        },
    )
    assert promoted.status_code == 201, promoted.text
    promoted_body = promoted.json()
    assert promoted_body["current_version"]["origin_kind"] == "message_promotion"
    assert promoted_body["current_version"]["source_message_id"] == assistant.id


def test_artifact_related_submitted_and_edit_keep_exact_historical_version(
    client: TestClient,
    db: Session,
    alice: User,
):
    job = _job(db, alice)
    confirmation = _message(
        db,
        alice,
        role="User",
        content="I submitted this exact resume version.",
        conversation_id="submission-conv",
    )
    created = client.post(
        "/api/v1/artifacts",
        json={
            "operation_key": "save-resume-1",
            "artifact_kind": "resume",
            "version": {"title": "Resume", "content_text": "version one"},
        },
    )
    artifact = created.json()
    artifact_id = artifact["id"]
    version_one_id = artifact["current_version"]["id"]

    related = client.post(
        f"/api/v1/artifacts/{artifact_id}/related",
        json={"job_opportunity_id": job.id},
    )
    assert related.status_code == 200, related.text

    submitted = client.post(
        f"/api/v1/artifacts/{artifact_id}/submitted",
        json={
            "operation_key": "submitted-resume-1",
            "artifact_version_id": version_one_id,
            "job_opportunity_id": job.id,
            "confirmation_message_id": confirmation.id,
        },
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["artifact_version_id"] == version_one_id

    edited = client.post(
        f"/api/v1/artifacts/{artifact_id}/versions",
        json={
            "operation_key": "edit-resume-1",
            "version": {"title": "Resume", "content_text": "version two"},
        },
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["current_version"]["id"] != version_one_id
    snapshot = db.query(ArtifactSubmissionSnapshot).one()
    assert snapshot.artifact_version_id == version_one_id

    versions = client.get(f"/api/v1/artifacts/{artifact_id}/versions")
    assert versions.status_code == 200
    assert [row["version_no"] for row in versions.json()] == [2, 1]
    assert all(row["created_at"] for row in versions.json())

    relations = client.get(f"/api/v1/artifacts/{artifact_id}/related")
    assert relations.status_code == 200
    assert relations.json()[0]["job_opportunity_id"] == job.id
    assert relations.json()[0]["created_at"]

    submissions = client.get(f"/api/v1/artifacts/{artifact_id}/submissions")
    assert submissions.status_code == 200
    assert submissions.json()[0]["artifact_version_id"] == version_one_id
    assert submissions.json()[0]["submitted_version"]["content_text"] == "version one"
    assert submissions.json()[0]["submitted_version"]["created_at"]

    archived = client.post(f"/api/v1/artifacts/{artifact_id}/archive")
    assert archived.status_code == 200
    assert archived.json()["archived_at"] is not None
    archived_detail = client.get(f"/api/v1/artifacts/{artifact_id}")
    assert archived_detail.status_code == 200
    assert archived_detail.json()["archived_at"] == archived.json()["archived_at"]
    assert client.get(f"/api/v1/artifacts/{artifact_id}/versions").status_code == 200
    assert (
        client.get(f"/api/v1/artifacts/{artifact_id}/submissions").json()[0][
            "artifact_version_id"
        ]
        == version_one_id
    )


def test_artifact_history_reads_do_not_cross_tenants(
    client: TestClient,
    db: Session,
):
    bob = User(username="bob", email="bob@example.com", hashed_password="x")
    db.add(bob)
    db.flush()
    artifact = artifact_service.save_artifact_explicitly(
        db,
        user_pk=bob.id,
        operation_key="bob-save",
        artifact_kind="resume",
        version=ArtifactWriteInput(title="Bob resume", content_text="private"),
    )
    db.commit()

    for suffix in ("versions", "related", "submissions"):
        response = client.get(f"/api/v1/artifacts/{artifact.id}/{suffix}")
        assert response.status_code == 404


def test_artifact_list_is_bounded_and_returns_current_versions_and_archive_state(
    client: TestClient,
    db: Session,
):
    first = client.post(
        "/api/v1/artifacts",
        json={
            "operation_key": "list-save-1",
            "artifact_kind": "resume",
            "version": {"title": "Resume", "content_text": "version one"},
        },
    ).json()
    second = client.post(
        "/api/v1/artifacts",
        json={
            "operation_key": "list-save-2",
            "artifact_kind": "report",
            "version": {"title": "Report", "content_text": "report body"},
        },
    ).json()
    edited = client.post(
        f"/api/v1/artifacts/{first['id']}/versions",
        json={
            "operation_key": "list-edit-1",
            "version": {"title": "Resume", "content_text": "version two"},
        },
    ).json()
    archived = client.post(f"/api/v1/artifacts/{second['id']}/archive").json()
    bob = User(username="list-bob", email="list-bob@example.com", hashed_password="x")
    db.add(bob)
    db.flush()
    hidden = artifact_service.save_artifact_explicitly(
        db,
        user_pk=bob.id,
        operation_key="list-bob-save",
        artifact_kind="report",
        version=ArtifactWriteInput(title="Bob report", content_text="private"),
    )
    db.commit()

    active = client.get("/api/v1/artifacts")
    assert active.status_code == 200, active.text
    assert active.json() == [edited]

    first_page = client.get(
        "/api/v1/artifacts",
        params={"include_archived": True, "limit": 1, "offset": 0},
    )
    second_page = client.get(
        "/api/v1/artifacts",
        params={"include_archived": True, "limit": 1, "offset": 1},
    )
    assert first_page.status_code == second_page.status_code == 200
    pages = first_page.json() + second_page.json()
    assert {item["id"] for item in pages} == {first["id"], second["id"]}
    assert hidden.id not in {item["id"] for item in pages}
    listed_archive = next(item for item in pages if item["id"] == second["id"])
    assert listed_archive["archived_at"] == archived["archived_at"]
    listed_current = next(item for item in pages if item["id"] == first["id"])
    assert listed_current["current_version"]["content_text"] == "version two"

    assert client.get("/api/v1/artifacts", params={"limit": 101}).status_code == 422


def test_artifact_relation_rejects_another_users_job(
    client: TestClient,
    db: Session,
    alice: User,
):
    bob = User(username="bob", email="bob@example.com", hashed_password="x")
    db.add(bob)
    db.commit()
    bob_job = _job(db, bob, "2")
    artifact_id = client.post(
        "/api/v1/artifacts",
        json={
            "operation_key": "save-1",
            "artifact_kind": "report",
            "version": {"title": "Report", "content_text": "body"},
        },
    ).json()["id"]

    response = client.post(
        f"/api/v1/artifacts/{artifact_id}/related",
        json={"job_opportunity_id": bob_job.id},
    )
    assert response.status_code == 404


def test_offer_http_returns_diff_then_requires_explicit_cas_confirmation(
    client: TestClient,
    db: Session,
    alice: User,
):
    job = _job(db, alice)
    initial_assertion = _message(
        db,
        alice,
        role="User",
        content="The written Offer says CNY 100000 gross annually.",
        conversation_id="offer-initial",
    )
    confirmation = _message(
        db,
        alice,
        role="User",
        content="Replace the current terms with the new written Offer.",
        conversation_id="offer-confirm",
    )
    candidate_file = _asset(db, alice, "fa-offer-replacement")

    created = client.post(
        f"/api/v1/career-process/opportunities/{job.id}/offer",
        json={
            "operation_key": "offer-create-1",
            "terms": _offer_terms("100000"),
            "source": _source("user_assertion", str(initial_assertion.id)),
        },
    )
    assert created.status_code == 200, created.text
    offer_id = created.json()["offer"]["id"]

    candidate_source = _source(
        "file_asset",
        candidate_file.id,
        f"sha256:{'a' * 64}",
    )
    conflict = client.post(
        f"/api/v1/career-process/opportunities/{job.id}/offer",
        json={
            "operation_key": "offer-source-2",
            "terms": _offer_terms("120000"),
            "source": candidate_source,
        },
    )
    assert conflict.status_code == 409, conflict.text
    detail = conflict.json()["detail"]
    assert detail["status"] == "confirmation_required"
    assert "base_salary_amount" in detail["diff"]["changed"]

    confirmed = client.post(
        f"/api/v1/career-process/opportunities/{job.id}/offer/confirm-terms",
        json={
            "offer_id": offer_id,
            "operation_key": "offer-confirm-2",
            "expected_current_token": detail["current_token"],
            "resolution": "replace",
            "terms": _offer_terms("120000"),
            "candidate_source": candidate_source,
            "confirmation_source": _source(
                "user_assertion",
                str(confirmation.id),
            ),
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["offer"]["id"] == offer_id
    assert confirmed.json()["offer"]["terms_json"]["base_salary_amount"] == "120000"
    assert len(confirmed.json()["offer"]["source_excerpts_json"]) == 2

    read = client.get(f"/api/v1/career-process/opportunities/{job.id}/offer")
    assert read.status_code == 200
    assert read.json()["current_token"] == confirmed.json()["current_token"]


def test_offer_diff_can_be_confirmed_by_typed_product_ui_command(
    client: TestClient,
    db: Session,
    alice: User,
):
    job = _job(db, alice)
    initial_assertion = _message(
        db,
        alice,
        role="User",
        content="The current written Offer is CNY 100000 gross annually.",
        conversation_id="offer-ui-initial",
    )
    candidate_file = _asset(db, alice, "fa-offer-ui-replacement")

    created = client.post(
        f"/api/v1/career-process/opportunities/{job.id}/offer",
        json={
            "operation_key": "offer-ui-create",
            "terms": _offer_terms("100000"),
            "source": _source("user_assertion", str(initial_assertion.id)),
        },
    )
    assert created.status_code == 200, created.text
    offer_id = created.json()["offer"]["id"]
    candidate_source = _source(
        "file_asset",
        candidate_file.id,
        f"sha256:{'a' * 64}",
    )
    conflict = client.post(
        f"/api/v1/career-process/opportunities/{job.id}/offer",
        json={
            "operation_key": "offer-ui-candidate",
            "terms": _offer_terms("120000"),
            "source": candidate_source,
        },
    )
    detail = conflict.json()["detail"]
    command = {
        "offer_id": offer_id,
        "operation_key": "offer-ui-confirm",
        "expected_current_token": detail["current_token"],
        "resolution": "replace",
        "terms": _offer_terms("120000"),
        "candidate_source": candidate_source,
        "ui_confirmation": {"kind": "product_ui"},
    }

    confirmed = client.post(
        f"/api/v1/career-process/opportunities/{job.id}/offer/confirm-terms",
        json=command,
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["offer"]["terms_json"]["base_salary_amount"] == "120000"
    row = db.query(Offer).filter(Offer.id == offer_id).one()
    assert row.last_confirmation_source_kind == "user_assertion"
    assert row.last_confirmation_source_identity == "product_ui:offer-ui-confirm"
    assert row.last_confirmation_source_version == detail["current_token"]

    replay = client.post(
        f"/api/v1/career-process/opportunities/{job.id}/offer/confirm-terms",
        json=command,
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["current_token"] == confirmed.json()["current_token"]

    stale = client.post(
        f"/api/v1/career-process/opportunities/{job.id}/offer/confirm-terms",
        json={**command, "operation_key": "offer-ui-stale"},
    )
    assert stale.status_code == 409


def test_offer_confirmation_requires_exactly_one_explicit_confirmation_mode(
    client: TestClient,
    db: Session,
    alice: User,
):
    job = _job(db, alice)
    response = client.post(
        f"/api/v1/career-process/opportunities/{job.id}/offer/confirm-terms",
        json={
            "offer_id": "of_00000000000000000000000000000000",
            "operation_key": "missing-confirmation",
            "expected_current_token": "a" * 64,
            "resolution": "replace",
            "terms": _offer_terms("120000"),
            "candidate_source": _source("file_asset", "not-used"),
        },
    )
    assert response.status_code == 422


def test_offer_http_fails_closed_for_unimplemented_source_owner(
    client: TestClient,
    db: Session,
    alice: User,
):
    job = _job(db, alice)
    response = client.post(
        f"/api/v1/career-process/opportunities/{job.id}/offer",
        json={
            "operation_key": "unverified-observation",
            "terms": _offer_terms("100000"),
            "source": _source("observation", "observation-does-not-exist"),
        },
    )
    assert response.status_code == 422
    assert db.query(Offer).count() == 0


def test_offer_http_accepts_only_owned_completed_tool_result_generation(
    client: TestClient,
    db: Session,
    alice: User,
):
    job = _job(db, alice)
    conversation = Conversation(
        id="tool-result-source",
        user_id=alice.id,
        title="source",
        type="general",
    )
    db.add(conversation)
    db.flush()
    turn = ConversationTurn(
        id="tool-result-source-turn",
        conversation_id=conversation.id,
        user_id=alice.id,
        mode="agent",
        message="Read the Offer",
        status="completed",
        dispatch_generation=2,
    )
    db.add(turn)
    db.flush()
    tool_call = AgentToolCall(
        call_id="read-offer-1",
        turn_id=turn.id,
        session_id=conversation.id,
        user_id=alice.id,
        tool_name="read_connected_offer",
        effect="read",
        arguments_json={},
        timeout_seconds=30,
        status="completed",
        dispatch_generation=2,
        policy_decision="allow",
        policy_reason="read_only",
        result_json={"original_text": "Annual gross base salary CNY 100000."},
        completed_at=NOW,
    )
    db.add(tool_call)
    db.commit()

    stale = client.post(
        f"/api/v1/career-process/opportunities/{job.id}/offer",
        json={
            "operation_key": "tool-result-stale-generation",
            "terms": _offer_terms("100000"),
            "source": _source("tool_result", str(tool_call.id), "1"),
        },
    )
    assert stale.status_code == 422
    assert db.query(Offer).count() == 0

    accepted = client.post(
        f"/api/v1/career-process/opportunities/{job.id}/offer",
        json={
            "operation_key": "tool-result-current-generation",
            "terms": _offer_terms("100000"),
            "source": _source("tool_result", str(tool_call.id), "2"),
        },
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["offer"]["last_source_identity"] == str(tool_call.id)


def test_terminal_job_keeps_offer_readable_but_rejects_term_changes(
    client: TestClient,
    db: Session,
    alice: User,
):
    job = _job(db, alice)
    assertion = _message(
        db,
        alice,
        role="User",
        content="This is the current Offer.",
        conversation_id="terminal-offer",
    )
    created = client.post(
        f"/api/v1/career-process/opportunities/{job.id}/offer",
        json={
            "operation_key": "offer-create",
            "terms": _offer_terms("100000"),
            "source": _source("user_assertion", str(assertion.id)),
        },
    )
    assert created.status_code == 200

    job.outcome = "accepted"
    job.archived_at = NOW
    db.add(job)
    db.commit()

    assert (
        client.get(f"/api/v1/career-process/opportunities/{job.id}/offer").status_code
        == 200
    )
    rejected_write = client.post(
        f"/api/v1/career-process/opportunities/{job.id}/offer",
        json={
            "operation_key": "late-change",
            "terms": _offer_terms("120000"),
            "source": _source("user_assertion", str(assertion.id)),
        },
    )
    assert rejected_write.status_code == 409
