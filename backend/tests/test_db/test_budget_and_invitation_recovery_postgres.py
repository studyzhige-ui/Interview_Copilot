"""PostgreSQL concurrency and actual process death at the Operation commit seam.

No live models, connectors or production databases are used. Every case uses
fresh_pg_db. REQUIRE_TEST_POSTGRES=1 makes an unavailable test database fail CI.
"""

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from alembic import command
from app.models.model_budget import ModelBudgetReservation, ModelBudgetWindow
from app.models.model_dispatch import AgentModelDispatch
from app.models.user import User
from app.services.chat import model_budget_service as budget
from app.services.chat import model_dispatch_service as dispatch
from tests.test_db.test_alembic_migrations import fresh_pg_db, _make_alembic_config  # noqa: F401
from tests.test_services.chat.test_model_dispatch_service import _turn
from tests.test_api.test_interview_invitations_api import _payload


@pytest.fixture
def database(fresh_pg_db):  # noqa: F811 -- imported fixture
    cfg = _make_alembic_config(fresh_pg_db)
    command.upgrade(cfg, "head")
    engine = create_engine(fresh_pg_db)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield fresh_pg_db, cfg, factory
    finally:
        engine.dispose()


def test_account_last_allowance_is_atomic_across_workers(database, monkeypatch):
    _, _, factory = database
    monkeypatch.setattr(budget.settings, "MODEL_DAILY_CALL_LIMIT", 1)
    monkeypatch.setattr(budget.settings, "MODEL_DAILY_TOKEN_LIMIT", 100)
    with factory() as db:
        owner = User(username="parallel-budget", hashed_password="x")
        db.add(owner)
        db.commit()
        user_id = owner.id
    barrier = Barrier(2)

    def attempt(index):
        with factory() as db:
            barrier.wait(timeout=10)
            try:
                budget.reserve(
                    db,
                    user_id=user_id,
                    turn_id=str(index),
                    call_id="1",
                    token_allowance=100,
                )
                db.commit()
                return "admitted"
            except budget.ModelBudgetExceededError:
                db.rollback()
                return "denied"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert sorted(results) == ["admitted", "denied"]
    with factory() as db:
        window = db.query(ModelBudgetWindow).one()
        assert (window.calls_admitted, window.tokens_reserved) == (1, 100)
        assert db.query(ModelBudgetReservation).count() == 1


def test_same_model_dispatch_only_one_worker_gets_a_permit(database):
    _, _, factory = database
    with factory() as db:
        user, turn = _turn(db)
        scope = dict(
            user_id=user.id,
            turn_id=turn.id,
            dispatch_generation=3,
            provider="fixture",
            model="fixture-model",
            call_id="one-call",
            fingerprint="a" * 64,
        )
    barrier = Barrier(2)

    def attempt(_):
        with factory() as db:
            barrier.wait(timeout=10)
            try:
                dispatch.start_model_dispatch(db, **scope)
                return "admitted"
            except dispatch.ModelDispatchConflictError:
                db.rollback()
                return "duplicate"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert sorted(results) == ["admitted", "duplicate"]
    with factory() as db:
        assert db.query(AgentModelDispatch).count() == 1
        assert db.query(ModelBudgetReservation).count() == 1


# Constant code only. Inputs contain synthetic fixture data and isolated DB URL.
# os._exit closes the process without finally/Session.rollback, unlike an
# exception-based SQLite simulation. The PostgreSQL connection owns rollback.
KILLED_WORKER = r"""
import json, os, sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.career.application import invitation_submission_service as ingress
from app.career.application import interview_invitation_operations as operations
from app.agent_runtime.tool_registry import AgentToolContext
from app.agent_runtime.tools import interview_invitation as tool
from app.agent_runtime.tools.interview_invitation import ReviewInterviewInvitationCandidateArgs
payload = json.load(sys.stdin)
factory = sessionmaker(bind=create_engine(payload["url"]), expire_on_commit=False)
if payload["phase"] == "verifying":
    def die(*args, **kwargs):
        os._exit(71)
    operations._verification = die
if payload["mode"] == "ui":
    with factory() as db:
        result = ingress.execute_submission(db, user_pk=payload["owner"], key=payload["key"])
        db.commit()
else:
    tool.SessionLocal = factory
    ctx = AgentToolContext(user_id=payload["username"], user_pk=payload["owner"],
        session_id=payload["conversation"], turn_id=payload["turn"], tool_call_id=payload["call"])
    result = tool._review_candidate_sync(ReviewInterviewInvitationCandidateArgs(
        candidate_id=payload["candidate"], expected_candidate_version=payload["candidate_version"]), ctx)
    if "error" in result:
        raise RuntimeError(result)
# Response deliberately never reaches the parent after the database commit.
os._exit(72)
"""


@pytest.mark.parametrize("mode", ["ui", "fixture_review"])
@pytest.mark.parametrize("phase", ["verifying", "committed"])
def test_process_kill_preserves_exact_operation_recovery(
    database, mode, phase, monkeypatch
):
    from app.career.application import invitation_submission_service as ingress
    from app.career.application.fixture_invitation_adapter import (
        ingest_fixture_interview_invitation,
    )
    from app.agent_runtime.tool_registry import AgentToolContext
    from app.agent_runtime.tools import interview_invitation as tool
    from app.agent_runtime.tools.interview_invitation import (
        ReviewInterviewInvitationCandidateArgs,
    )
    from app.models.agent_interaction import AgentInteraction
    from app.models.application_operation import (
        ApplicationOperation,
        OperationVerification,
    )
    from app.models.interview_record import InterviewRecord
    from app.models.job_opportunity import JobOpportunity, NextAction
    from app.schemas.interview_invitation import (
        ConfirmInterviewInvitation,
        FixtureInterviewInvitationInput,
        FactConfirmationResolution,
    )
    from app.services.chat.interaction_service import resolve_interaction

    url, _, factory = database
    payload = dict(url=url, mode=mode, phase=phase, key="exact-browser-request")
    raw_command = _payload(payload["key"])
    with factory() as db:
        user = User(username="kill-recovery-owner", hashed_password="x")
        db.add(user)
        db.commit()
        payload.update(owner=user.id, username=user.username)
        if mode == "ui":
            ingress.register_submission(
                db,
                user_pk=user.id,
                command=ConfirmInterviewInvitation.model_validate(raw_command),
            )
        else:
            fixture = ingest_fixture_interview_invitation(
                db,
                user_pk=user.id,
                command=FixtureInterviewInvitationInput(
                    idempotency_key="fixture-ingress",
                    source_identity="fixture-recruiter-message",
                    source_version="1",
                    observed_at=raw_command["asserted_at"],
                    raw_payload={"subject": "Synthetic invitation, not an instruction"},
                    extracted_facts=raw_command["facts"],
                    extractor_version="test@1",
                ),
            )
            interaction = db.get(AgentInteraction, fixture.interaction.id)
            resolve_interaction(
                db,
                interaction_id=interaction.id,
                user_id=user.id,
                expected_version=interaction.version,
                status="resolved",
                resolution=FactConfirmationResolution(
                    decision="confirm", opportunity={"kind": "create_new"}
                ),
                resolution_identity="explicit-fixture-user-decision",
            )
            payload.update(
                candidate=fixture.candidate.id,
                candidate_version=fixture.candidate.version,
                conversation=fixture.conversation_id,
                turn=fixture.turn_id,
                call=f"fixture-review:{fixture.candidate.id}",
            )
            db.commit()
    crashed = subprocess.run(
        [sys.executable, "-c", KILLED_WORKER],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert crashed.returncode == (71 if phase == "verifying" else 72), crashed.stderr
    with factory() as db:
        expected = 0 if phase == "verifying" else 1
        assert db.query(InterviewRecord).count() == expected
        assert db.query(JobOpportunity).count() == expected
        assert db.query(NextAction).count() == 0
        confirms = (
            db.query(ApplicationOperation)
            .filter_by(operation_name="confirm_interview_invitation")
            .all()
        )
        assert len(confirms) == expected
        if confirms:
            assert confirms[0].status == "succeeded"
            assert (
                db.query(OperationVerification)
                .filter_by(operation_id=confirms[0].id, conclusion="verified")
                .count()
                == 1
            )
    if mode == "ui":
        with factory() as db:
            # GET does not re-run the operation.
            receipt = ingress.submission_view(
                db, user_pk=payload["owner"], key=payload["key"]
            )
            assert receipt["status"] == (
                "pending" if phase == "verifying" else "committed"
            )
            result = ingress.execute_submission(
                db, user_pk=payload["owner"], key=payload["key"]
            )
            db.commit()
            first_id = result.operation_id
    else:
        monkeypatch.setattr(tool, "SessionLocal", factory)
        ctx = AgentToolContext(
            user_id=payload["username"],
            user_pk=payload["owner"],
            session_id=payload["conversation"],
            turn_id=payload["turn"],
            tool_call_id=payload["call"],
        )
        args = ReviewInterviewInvitationCandidateArgs(
            candidate_id=payload["candidate"],
            expected_candidate_version=payload["candidate_version"],
        )
        result = tool._review_candidate_sync(args, ctx)
        assert "error" not in result, result
        first_id = result["operation"]["operation_id"]
    with factory() as db:
        assert db.query(InterviewRecord).count() == 1
        assert db.query(JobOpportunity).count() == 1
        assert db.query(NextAction).count() == 0
        assert (
            db.execute(
                select(ApplicationOperation.id).where(
                    ApplicationOperation.operation_name
                    == "confirm_interview_invitation"
                )
            ).scalar_one()
            == first_id
        )


def test_additive_migrations_keep_existing_facts_on_up_down_up(fresh_pg_db):  # noqa: F811
    cfg = _make_alembic_config(fresh_pg_db)
    command.upgrade(cfg, "0047")
    engine = create_engine(fresh_pg_db)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        user = User(username="retained-user", hashed_password="x")
        db.add(user)
        db.commit()
    command.upgrade(cfg, "head")
    command.check(cfg)
    command.downgrade(cfg, "0047")
    command.upgrade(cfg, "head")
    command.check(cfg)
    with factory() as db:
        assert db.query(User).filter_by(username="retained-user").count() == 1
    engine.dispose()
