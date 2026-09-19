"""Real PostgreSQL lease admission, stale owners and historical migration."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

from sqlalchemy import MetaData, Table

from alembic import command
from app.db.types import utc_now
from app.models.mock_interview_runtime import MockInterviewRuntime
from app.models.interview_record import InterviewRecord
from app.models.user import User
from app.services.interview import mock_runtime_service as runtime_service
from tests.test_db.test_budget_and_invitation_recovery_postgres import (
    database as database_fixture,
)
from tests.test_db.test_alembic_migrations import fresh_pg_db  # noqa: F401
from tests.test_services.interview.test_mock_flow_phase5 import _make_run

database = database_fixture


def seed(factory):
    with factory() as db:
        db.add(User(username="alice", hashed_password="x"))
        db.commit()
        record, runtime, _ = _make_run(db)
        return record.id, runtime.current_question_message_id


def test_two_answer_workers_only_one_owns_question(database):
    _, _, factory = database
    record_id, question = seed(factory)
    barrier = Barrier(2)

    def claim(_):
        with factory() as db:
            runtime = db.get(MockInterviewRuntime, record_id)
            barrier.wait(timeout=10)
            result = runtime_service.claim_question(
                db, runtime, question_message_id=question
            )
            generation = runtime.answer_claim_generation
            db.commit()
            return result, generation

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(claim, range(2)))
    assert sorted(outcome[0] for outcome in outcomes) == ["busy", "claimed"]
    with factory() as db:
        runtime = db.get(MockInterviewRuntime, record_id)
        assert runtime.answer_claim_generation == 1
        assert runtime.answer_claimed_at is not None


def test_late_owner_cannot_release_successor_or_publish_after_finish(database):
    _, _, factory = database
    record_id, question = seed(factory)
    with factory() as first:
        old_runtime = first.get(MockInterviewRuntime, record_id)
        assert (
            runtime_service.claim_question(
                first, old_runtime, question_message_id=question
            )
            == "claimed"
        )
        old_generation = old_runtime.answer_claim_generation
        old_runtime.answer_claimed_at = utc_now() - timedelta(minutes=11)
        first.commit()
        with factory() as second:
            current = second.get(MockInterviewRuntime, record_id)
            assert (
                runtime_service.claim_question(
                    second, current, question_message_id=question
                )
                == "claimed"
            )
            new_generation = current.answer_claim_generation
            second.commit()
        assert new_generation == old_generation + 1
        runtime_service.release_question_claim(
            first,
            record_id,
            question_message_id=question,
            claim_generation=old_generation,
        )
        assert (
            runtime_service.lock_question_lease(
                first,
                interview_record_id=record_id,
                question_message_id=question,
                claim_generation=old_generation,
            )
            is None
        )
        first.rollback()
        with factory() as second:
            current = second.get(MockInterviewRuntime, record_id)
            assert current.answer_claimed_at is not None
            assert current.answer_claim_generation == new_generation
            owned = runtime_service.lock_question_lease(
                second,
                interview_record_id=record_id,
                question_message_id=question,
                claim_generation=new_generation,
            )
            assert owned is not None
            second.get(InterviewRecord, record_id).status = "processing_review"
            second.commit()
        assert (
            runtime_service.lock_question_lease(
                first,
                interview_record_id=record_id,
                question_message_id=question,
                claim_generation=new_generation,
            )
            is None
        )


def test_upgrade_adds_fence_without_rewriting_runtime_or_transcript(database):
    _, cfg, factory = database
    record_id, _ = seed(factory)
    command.downgrade(cfg, "0050")
    with factory() as db:
        table = Table(
            "mock_interview_runtime", MetaData(), autoload_with=db.connection()
        )
        before = dict(
            db.execute(table.select().where(table.c.interview_record_id == record_id))
            .mappings()
            .one()
        )
        assert "answer_claim_generation" not in before
    command.upgrade(cfg, "head")
    command.check(cfg)
    with factory() as db:
        table = Table(
            "mock_interview_runtime", MetaData(), autoload_with=db.connection()
        )
        after = dict(
            db.execute(table.select().where(table.c.interview_record_id == record_id))
            .mappings()
            .one()
        )
        assert after.pop("answer_claim_generation") == 0
        assert after == before
