"""Real PostgreSQL contracts for source correction; mandatory when CI requires PG.

SQLite unit tests do not establish row-lock or migration guarantees. These cases
use the repository's existing isolated database fixture, never production data.
"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import json

import pytest
from sqlalchemy import text
from alembic import command
from app.core.command_errors import CommandError
from app.models.user import User
from app.models.interview_record import InterviewRecord
from app.models.interview_qa import InterviewQA
from app.models.interview_qa_revision import InterviewQARevision
from app.schemas.interview import QAEditRequest
from app.interviews.application.corrections import edit_qa
from app.interviews.application.review_fence import (
    lock_record,
    review_scope,
    ReviewSuperseded,
)
from tests.test_db.test_budget_and_invitation_recovery_postgres import (
    database as database_fixture,
)
from tests.test_db.test_alembic_migrations import fresh_pg_db  # noqa: F401

database = database_fixture


def seed(factory):
    with factory() as db:
        owner = User(username="review-cas-owner", hashed_password="fixture")
        db.add(owner)
        db.flush()
        record = InterviewRecord(
            user_id=owner.id,
            source="upload",
            status="completed",
            analysis_json='{"overall":{"score":8}}',
        )
        db.add(record)
        db.flush()
        qa = InterviewQA(
            record_id=record.id, order_idx=0, question="问题", answer="原答案", score=8
        )
        db.add(qa)
        db.commit()
        return owner.id, record.id, qa.id


def test_two_editors_cannot_overwrite_one_another(database):
    _, _, factory = database
    owner_id, record_id, qa_id = seed(factory)
    barrier = Barrier(2)

    def edit(index):
        with factory() as db:
            owner = db.get(User, owner_id)
            db.execute(text("SET LOCAL lock_timeout = '8s'"))
            barrier.wait(timeout=10)
            try:
                edit_qa(
                    db,
                    record_id=record_id,
                    qa_id=qa_id,
                    current_user=owner,
                    payload=QAEditRequest(expected_version=1, answer=f"新答案{index}"),
                )
                return "saved"
            except CommandError as error:
                db.rollback()
                assert error.kind == "conflict"
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(edit, range(2))) == ["conflict", "saved"]
    with factory() as db:
        assert db.get(InterviewQA, qa_id).version == 2
        assert db.query(InterviewQARevision).filter_by(record_id=record_id).count() == 1
        assert db.get(InterviewRecord, record_id).analysis_json is None


def test_prior_worker_identity_cannot_publish_after_correction(database):
    _, _, factory = database
    owner_id, record_id, qa_id = seed(factory)
    with factory() as worker:
        generation = worker.get(InterviewRecord, record_id).review_generation
        worker.commit()  # Provider would run without a transaction here.
        with factory() as editor:
            edit_qa(
                editor,
                record_id=record_id,
                qa_id=qa_id,
                current_user=editor.get(User, owner_id),
                payload=QAEditRequest(expected_version=1, answer="唯一现行答案"),
            )
        with review_scope(record_id, generation), pytest.raises(ReviewSuperseded):
            lock_record(worker, record_id)
        worker.rollback()
    with factory() as db:
        assert db.get(InterviewQA, qa_id).answer == "唯一现行答案"
        assert db.get(InterviewQA, qa_id).score is None


def test_upgrade_preserves_legacy_answers_and_requires_export_for_new_history(database):
    _, cfg, factory = database
    owner_id, record_id, qa_id = seed(factory)
    # No new source versions/history yet: a rollback for migration testing is safe.
    command.downgrade(cfg, "0052")
    with factory() as db:
        before = dict(
            db.execute(
                text(
                    "SELECT id, question, answer, score FROM interview_qa WHERE id=:id"
                ),
                {"id": qa_id},
            )
            .mappings()
            .one()
        )
    command.upgrade(cfg, "head")
    command.check(cfg)
    with factory() as db:
        after = dict(
            db.execute(
                text(
                    "SELECT id, question, answer, score FROM interview_qa WHERE id=:id"
                ),
                {"id": qa_id},
            )
            .mappings()
            .one()
        )
        assert before == after
        assert db.get(InterviewRecord, record_id).specification_json is None
        assert db.get(InterviewQA, qa_id).version == 1
        edit_qa(
            db,
            record_id=record_id,
            qa_id=qa_id,
            current_user=db.get(User, owner_id),
            payload=QAEditRequest(expected_version=1, answer="已修正"),
        )
    with pytest.raises(RuntimeError, match="requires_export"):
        command.downgrade(cfg, "0052")
    with factory() as db:
        receipt = db.query(InterviewQARevision).one()
        assert receipt.before_json["answer"] == before["answer"]
        assert (
            json.loads(receipt.invalidated_review_json["report"])["overall"]["score"]
            == 8
        )
