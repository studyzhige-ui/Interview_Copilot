from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  # register every FK target on shared metadata
from app.db.database import Base
from app.models.agent_execution import AgentToolCall
from app.models.job_description_snapshot import (
    JobDescriptionSnapshotImmutableError,
)
from app.models.job_opportunity import JobOpportunity
from app.schemas.job_description_snapshot import (
    JobDescriptionSnapshotFromProductUI,
    JobDescriptionSnapshotFromToolResult,
)
from app.services.job_description_snapshot_service import (
    JobDescriptionSnapshotError,
    create_job_description_snapshot,
    list_job_description_snapshots,
)


@pytest.fixture()
def db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


def _opportunity(db: Session, *, owner: int = 1) -> JobOpportunity:
    row = JobOpportunity(
        id="opp_snapshot_test",
        user_id=owner,
        company_name="Example",
        job_title="Backend Engineer",
    )
    db.add(row)
    db.flush()
    return row


def _command(
    *, content: str, idempotency_key: str
) -> JobDescriptionSnapshotFromProductUI:
    return JobDescriptionSnapshotFromProductUI(
        source_kind="typed_product_ui",
        source_identity="product-ui:job-detail",
        source_version="1",
        original_url="HTTPS://jobs.example.test/opening/1#apply",
        observed_at=datetime(2026, 8, 13, tzinfo=timezone.utc),
        provider="product_ui",
        canonical_content=content,
        idempotency_key=idempotency_key,
    )


def test_product_ui_snapshot_is_versioned_and_idempotent(db: Session) -> None:
    opportunity = _opportunity(db)
    command = _command(content="Backend engineer JD", idempotency_key="jd-v1")

    first = create_job_description_snapshot(
        db,
        user_pk=1,
        opportunity_id=opportunity.id,
        command=command,
    )
    retry = create_job_description_snapshot(
        db,
        user_pk=1,
        opportunity_id=opportunity.id,
        command=command,
    )
    second = create_job_description_snapshot(
        db,
        user_pk=1,
        opportunity_id=opportunity.id,
        command=_command(
            content="Backend engineer JD, revised", idempotency_key="jd-v2"
        ),
    )

    assert retry.id == first.id
    assert (first.version, second.version) == (1, 2)
    assert first.content_checksum != second.content_checksum
    assert first.normalized_url == "https://jobs.example.test/opening/1"


def test_idempotency_key_rejects_changed_snapshot(db: Session) -> None:
    opportunity = _opportunity(db)
    create_job_description_snapshot(
        db,
        user_pk=1,
        opportunity_id=opportunity.id,
        command=_command(content="original", idempotency_key="same-command"),
    )

    with pytest.raises(JobDescriptionSnapshotError):
        create_job_description_snapshot(
            db,
            user_pk=1,
            opportunity_id=opportunity.id,
            command=_command(content="changed", idempotency_key="same-command"),
        )


def test_snapshot_queries_are_owner_scoped(db: Session) -> None:
    opportunity = _opportunity(db)
    create_job_description_snapshot(
        db,
        user_pk=1,
        opportunity_id=opportunity.id,
        command=_command(content="private JD", idempotency_key="private"),
    )

    with pytest.raises(JobDescriptionSnapshotError):
        list_job_description_snapshots(
            db,
            user_pk=2,
            opportunity_id=opportunity.id,
        )


def test_exact_owned_tool_result_can_be_promoted_without_model_copied_content(
    db: Session,
) -> None:
    opportunity = _opportunity(db)
    call = AgentToolCall(
        call_id="call-jd-detail",
        turn_id="turn-jd-detail",
        session_id="conversation-jd-detail",
        user_id=1,
        tool_name="search_jobs",
        effect="read",
        arguments_json={"job_id": "job-1"},
        timeout_seconds=20,
        status="completed",
        completed_at=datetime(2026, 8, 13, 8, 59, tzinfo=timezone.utc),
        policy_decision="allow",
        policy_reason="read_allowed",
        result_json={
            "site": "example",
            "job_id": "job-1",
            "hosted_url": "https://jobs.example.test/opening/1",
            "description_plain": "Exact provider JD body",
        },
    )
    db.add(call)
    db.flush()

    snapshot = create_job_description_snapshot(
        db,
        user_pk=1,
        opportunity_id=opportunity.id,
        command=JobDescriptionSnapshotFromToolResult(
            source_identity=call.call_id,
            tool_session_id=call.session_id,
            original_url="https://jobs.example.test/opening/1",
            observed_at=datetime(2026, 8, 13, 9, 0, tzinfo=timezone.utc),
            idempotency_key="promote-owned-tool-result",
        ),
    )

    assert snapshot.canonical_content == "Exact provider JD body"
    assert snapshot.source_identity == f"agent_tool_call:{call.id}"
    assert snapshot.source_version.startswith("generation:1:completed:")

    with pytest.raises(JobDescriptionSnapshotError):
        create_job_description_snapshot(
            db,
            user_pk=2,
            opportunity_id=opportunity.id,
            command=JobDescriptionSnapshotFromToolResult(
                source_identity=call.call_id,
                tool_session_id=call.session_id,
                original_url="https://jobs.example.test/opening/1",
                observed_at=datetime(2026, 8, 13, 9, 0, tzinfo=timezone.utc),
                idempotency_key="cross-tenant-tool-result",
            ),
        )


def test_snapshot_rows_cannot_be_rewritten_or_deleted(db: Session) -> None:
    opportunity = _opportunity(db)
    snapshot = create_job_description_snapshot(
        db,
        user_pk=1,
        opportunity_id=opportunity.id,
        command=_command(content="immutable JD", idempotency_key="immutable"),
    )
    db.commit()

    snapshot.provider = "rewritten"
    with pytest.raises(JobDescriptionSnapshotImmutableError):
        db.flush()
    db.rollback()

    snapshot = list_job_description_snapshots(
        db,
        user_pk=1,
        opportunity_id=opportunity.id,
    )[0]
    db.delete(snapshot)
    with pytest.raises(JobDescriptionSnapshotImmutableError):
        db.flush()
