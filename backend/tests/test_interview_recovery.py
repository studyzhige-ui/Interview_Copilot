"""A failed extraction checkpoint must not become valid merely by retrying."""

import pytest
import importlib

from app.models.interview_record import InterviewRecord
from app.models.interview_transcript import InterviewTranscript
from app.models.interview_qa import InterviewQA

module = importlib.import_module("app.interviews.application.analysis_orchestrator")


@pytest.mark.parametrize(
    "quality", [None, {}, {"status": "partial"}, {"status": "complete"}]
)
def test_retry_reuses_only_qa_from_complete_projection(
    db, owners, monkeypatch, quality
):
    record = InterviewRecord(user_id=owners[0].id, source="upload")
    db.add(record)
    db.flush()
    transcript = InterviewTranscript(
        record_id=record.id, user_id=owners[0].id, quality_json=quality
    )
    db.add(transcript)
    db.flush()
    db.add(
        InterviewQA(
            record_id=record.id,
            question="Question",
            answer="Answer",
            source_transcript_id=transcript.id,
            source_provenance_json={"words": ["w1"]},
        )
    )
    db.flush()
    # The helper owns and closes its session; keep the test transaction alive.
    monkeypatch.setattr(module, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    result = module.analysis_orchestrator._load_existing_qa_shells(
        record.id, source_transcript_id=transcript.id, require_provenance=True
    )
    assert bool(result) is (quality == {"status": "complete"})


def test_follow_up_relationship_survives_persistence_and_recovery(
    db, owners, monkeypatch
):
    record = InterviewRecord(user_id=owners[0].id, source="mock")
    db.add(record)
    db.flush()
    rows = module.interview_record_service.bulk_insert_qa(
        record.id,
        [
            {"question": "项目是什么？", "answer": "文档检索。"},
            {
                "question": "如何验证？",
                "answer": "隔离和删除测试。",
                "parent_index": 1,
                "is_follow_up": True,
            },
        ],
        db=db,
    )
    assert rows[1].parent_qa_id == rows[0].id
    assert rows[1].follow_up_depth == 1
    monkeypatch.setattr(module, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    recovered = module.analysis_orchestrator._load_existing_qa_shells(record.id)
    assert recovered[1]["parent_index"] == 1
    assert recovered[1]["is_follow_up"] is True


@pytest.mark.parametrize("outcome", ["success", "insert_failure", "superseded"])
def test_recording_checkpoint_publishes_atomically(db, owners, monkeypatch, outcome):
    from sqlalchemy.orm import Session
    from app.interviews.application.review_fence import ReviewSuperseded

    persistence = importlib.import_module(
        "app.interviews.application.interview_record_service"
    )
    record = InterviewRecord(user_id=owners[0].id, source="upload")
    db.add(record)
    db.flush()
    transcript = InterviewTranscript(
        record_id=record.id, user_id=owners[0].id, quality_json={"status": "partial"}
    )
    db.add(transcript)
    db.flush()
    record.transcript_id = transcript.id
    old = InterviewQA(
        record_id=record.id, question="Old partial question", answer="Old"
    )
    db.add(old)
    db.flush()
    old_id, record_id, transcript_id = old.id, record.id, transcript.id
    connection = db.connection()
    monkeypatch.setattr(
        persistence,
        "SessionLocal",
        lambda: Session(bind=connection, join_transaction_mode="create_savepoint"),
    )
    service = persistence.interview_record_service
    insert = service.bulk_insert_qa
    if outcome == "insert_failure":

        def fail_after_insert(*args, **kwargs):
            insert(*args, **kwargs)
            raise RuntimeError("simulated failure after QA flush")

        monkeypatch.setattr(service, "bulk_insert_qa", fail_after_insert)
    if outcome == "superseded":
        record.transcript_id = None
        db.flush()

    def publish():
        service.publish_recording_qa(
            record_id,
            transcript_id,
            structure={"schema_version": 2, "speaker_roles": []},
            quality={"status": "complete", "warnings": []},
            qa_pairs=[{"question": "New question", "answer": "New answer"}],
        )

    if outcome == "success":
        publish()
    else:
        with pytest.raises(
            ReviewSuperseded if outcome == "superseded" else RuntimeError
        ):
            publish()
    db.expire_all()
    rows = db.query(InterviewQA).filter_by(record_id=record_id).all()
    assert len(rows) == 1
    current = db.get(InterviewTranscript, transcript_id)
    if outcome == "success":
        assert rows[0].question == "New question" and rows[0].id != old_id
        assert rows[0].source_transcript_id == transcript_id
        assert current.quality_json["status"] == "complete"
    else:
        assert rows[0].id == old_id and rows[0].answer == "Old"
        assert current.quality_json == {"status": "partial"}
