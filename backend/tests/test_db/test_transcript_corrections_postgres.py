"""Real row locks and migration preservation; shared conftest owns the fixtures."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from alembic import command as migration
from app.core.command_errors import CommandError
from app.models.interview_record import InterviewRecord
from app.models.interview_transcript import InterviewTranscript
from app.models.transcript_correction import TranscriptCorrection
from app.interviews.application.transcript_corrections import (
    correct_transcript,
    get_receipt,
)
from app.interviews.application.review_fence import (
    lock_record,
    review_scope,
    ReviewSuperseded,
)
from tests.test_services.interview.test_transcript_corrections import seed, command


def initialize(factory):
    with factory() as db:
        owner, _, record, tr, _ = seed(db)
        return owner.id, record.id, tr.id, command(tr)


def test_two_transcript_editors_have_one_current_version(database):
    _, _, factory = database
    user_pk, record_id, tr_id, cmd = initialize(factory)
    import uuid

    barrier = Barrier(2)

    def attempt(index):
        request = cmd.model_copy(
            update={"request_id": str(uuid.uuid4()), "reason": f"editor {index}"}
        )
        with factory() as db:
            barrier.wait(timeout=10)
            try:
                correct_transcript(
                    db, record_id=record_id, user_pk=user_pk, command=request
                )
                return "saved"
            except CommandError as exc:
                db.rollback()
                assert exc.kind == "conflict"
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, range(2))) == ["conflict", "saved"]
    with factory() as db:
        assert db.query(TranscriptCorrection).count() == 1
        assert db.query(InterviewTranscript).count() == 2
        assert (
            db.get(InterviewTranscript, tr_id).evidence_json["words"][3]["text"]
            == "负责"
        )


def test_commit_reply_loss_uses_original_receipt(database):
    _, _, factory = database
    user_pk, record_id, _, cmd = initialize(factory)
    with factory() as db:
        original_commit = db.commit

        def lost_reply():
            original_commit()
            raise OSError("synthetic confirmation loss after durable commit")

        db.commit = lost_reply
        with pytest.raises(OSError):
            correct_transcript(db, record_id=record_id, user_pk=user_pk, command=cmd)
    with factory() as db:
        first = get_receipt(
            db, record_id=record_id, user_pk=user_pk, request_id=cmd.request_id
        )
        second = correct_transcript(
            db, record_id=record_id, user_pk=user_pk, command=cmd
        )
        assert first == second
        assert db.query(TranscriptCorrection).count() == 1


def test_prior_review_generation_cannot_publish_after_source_correction(database):
    _, _, factory = database
    user_pk, record_id, _, cmd = initialize(factory)
    with factory() as worker:
        generation = worker.get(InterviewRecord, record_id).review_generation
        worker.commit()
        with factory() as editor:
            correct_transcript(
                editor, record_id=record_id, user_pk=user_pk, command=cmd
            )
        with review_scope(record_id, generation), pytest.raises(ReviewSuperseded):
            lock_record(worker, record_id)


def test_0057_preserves_old_evidence_and_refuses_to_drop_nonempty_history(database):
    _, cfg, factory = database
    user_pk, record_id, tr_id, cmd = initialize(factory)
    with factory() as db:
        original = db.get(InterviewTranscript, tr_id).evidence_json
    migration.downgrade(cfg, "0056")
    migration.upgrade(cfg, "head")
    migration.check(cfg)
    with factory() as db:
        assert db.get(InterviewTranscript, tr_id).evidence_json == original
        correct_transcript(db, record_id=record_id, user_pk=user_pk, command=cmd)
    with pytest.raises(RuntimeError, match="requires_export"):
        migration.downgrade(cfg, "0056")
    with factory() as db:
        assert db.get(InterviewTranscript, tr_id).evidence_json == original
        assert db.query(TranscriptCorrection).count() == 1
