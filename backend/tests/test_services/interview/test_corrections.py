from types import SimpleNamespace
import json
from importlib import import_module
import pytest
from pydantic import ValidationError
from app.core.command_errors import CommandError
from app.models.user import User
from app.models.interview_record import InterviewRecord
from app.models.interview_qa import InterviewQA
from app.models.interview_qa_revision import InterviewQARevision
from app.schemas.interview import QAEditRequest
from app.interviews.application.corrections import edit_qa, list_corrections
from app.interviews.application.review_fence import (
    lock_record,
    review_scope,
    ReviewSuperseded,
)
from app.interviews.application.review_dispatch import dispatch_review_command


@pytest.fixture
def rows(db_session):
    user = User(username="correction-owner", hashed_password="x")
    stranger = User(username="correction-other", hashed_password="x")
    db_session.add_all([user, stranger])
    db_session.flush()
    record = InterviewRecord(
        user_id=user.id,
        source="mock",
        status="review_ready",
        analysis_json='{"overall":{"score":8}}',
    )
    db_session.add(record)
    db_session.flush()
    qa = InterviewQA(
        record_id=record.id,
        order_idx=0,
        question="什么是API?",
        answer="原回答",
        score=8,
        critique="旧评语",
        improved_answer="旧改进",
    )
    sibling = InterviewQA(
        record_id=record.id,
        order_idx=1,
        question="继续",
        answer="回答二",
        score=7,
        critique="另一评语",
    )
    db_session.add_all([qa, sibling])
    db_session.commit()
    return user, stranger, record, qa, sibling


def test_correction_archives_and_invalidates_without_model_or_queue(db_session, rows):
    user, _, record, qa, sibling = rows
    old_generation = record.review_generation
    result = edit_qa(
        db_session,
        record_id=record.id,
        qa_id=qa.id,
        current_user=user,
        payload=QAEditRequest(expected_version=1, answer="更正回答"),
    )
    assert result.answer == "更正回答" and result.version == 2
    assert result.score is None and result.critique is None
    assert sibling.score is None and sibling.version == 2
    assert record.analysis_json is None and record.status == "review_failed"
    assert record.review_generation == old_generation + 1
    receipt = db_session.query(InterviewQARevision).one()
    assert receipt.before_json["answer"] == "原回答"
    assert receipt.after_json["answer"] == "更正回答"
    assert (
        json.loads(receipt.invalidated_review_json["report"])["overall"]["score"] == 8
    )
    assert receipt.invalidated_review_json["questions"][1]["score"] == 7


def test_stale_editor_cannot_restore_old_answer(db_session, rows):
    user, _, record, qa, _ = rows
    edit_qa(
        db_session,
        record_id=record.id,
        qa_id=qa.id,
        current_user=user,
        payload=QAEditRequest(expected_version=1, answer="更正回答"),
    )
    with pytest.raises(CommandError) as error:
        edit_qa(
            db_session,
            record_id=record.id,
            qa_id=qa.id,
            current_user=user,
            payload=QAEditRequest(expected_version=1, answer="过期回答"),
        )
    assert error.value.kind == "conflict" and qa.answer == "更正回答"
    assert db_session.query(InterviewQARevision).count() == 1


def test_other_account_cannot_read_or_edit_history(db_session, rows):
    user, stranger, record, qa, _ = rows
    for operation in (
        lambda: edit_qa(
            db_session,
            record_id=record.id,
            qa_id=qa.id,
            current_user=stranger,
            payload=QAEditRequest(expected_version=1, answer="bad"),
        ),
        lambda: list_corrections(db_session, record_id=record.id, user_pk=stranger.id),
    ):
        with pytest.raises(CommandError) as error:
            operation()
        assert error.value.kind == "not_found"
    assert qa.version == 1


def test_unchanged_edit_is_not_a_revision(db_session, rows):
    user, _, record, qa, _ = rows
    edit_qa(
        db_session,
        record_id=record.id,
        qa_id=qa.id,
        current_user=user,
        payload=QAEditRequest(expected_version=1, answer=qa.answer),
    )
    assert qa.version == 1 and db_session.query(InterviewQARevision).count() == 0


def test_history_cursor_is_owned_and_bounded(db_session, rows):
    user, _, record, qa, _ = rows
    for answer in ("第二版", "第三版", "第四版"):
        edit_qa(
            db_session,
            record_id=record.id,
            qa_id=qa.id,
            current_user=user,
            payload=QAEditRequest(expected_version=qa.version, answer=answer),
        )
    page = list_corrections(db_session, record_id=record.id, user_pk=user.id, limit=1)
    assert len(page["items"]) == 1 and page["next_cursor"]
    next_page = list_corrections(
        db_session,
        record_id=record.id,
        user_pk=user.id,
        limit=1,
        before=page["next_cursor"],
    )
    assert next_page["items"][0]["new_version"] < page["items"][0]["new_version"]
    with pytest.raises(CommandError):
        list_corrections(
            db_session, record_id=record.id, user_pk=user.id, before="not-a-receipt"
        )


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"expected_version": True, "answer": "x"},
        {"expected_version": "1", "answer": "x"},
        {"expected_version": 1},
        {"expected_version": 1, "question": "  "},
        {"expected_version": 1, "answer": "x", "unexpected": 1},
    ],
)
def test_edit_requires_strict_version_and_meaningful_input(payload):
    with pytest.raises(ValidationError):
        QAEditRequest.model_validate(payload)


def test_old_review_cannot_write_status_or_results_after_correction(
    db_session, rows, monkeypatch
):
    user, _, record, qa, _ = rows
    generation = record.review_generation
    edit_qa(
        db_session,
        record_id=record.id,
        qa_id=qa.id,
        current_user=user,
        payload=QAEditRequest(expected_version=1, answer="新回答"),
    )
    orchestrator = import_module("app.interviews.application.analysis_orchestrator")
    service = import_module("app.interviews.application.interview_record_service")

    class NoClose:
        def __getattr__(self, name):
            return getattr(db_session, name)

        def close(self):
            pass

    monkeypatch.setattr(orchestrator, "SessionLocal", lambda: NoClose())
    with review_scope(record.id, generation):
        with pytest.raises(ReviewSuperseded):
            service.interview_record_service.set_status(
                record.id, "completed", db=db_session
            )
        with pytest.raises(ReviewSuperseded):
            orchestrator.analysis_orchestrator._persist_analysis(
                record.id, {"per_question": [{"score": 10}]}
            )
    assert record.analysis_json is None and qa.score is None
    assert qa.answer == "新回答"


def test_scope_does_not_leak_to_next_operation(db_session, rows):
    _, _, record, _, _ = rows
    with review_scope(record.id, 99):
        with pytest.raises(ReviewSuperseded):
            lock_record(db_session, record.id)
    assert lock_record(db_session, record.id).id == record.id


def test_dispatch_admission_is_durable_before_sender_and_does_not_rewind_success(
    db_session, rows
):
    _, _, record, _, _ = rows
    record.status = "processing_review"
    db_session.commit()

    def sender(record_id, *, task_id, review_generation):
        row = db_session.get(InterviewRecord, record_id)
        assert (
            row.celery_task_id == task_id and row.review_generation == review_generation
        )
        row.status = "review_ready"
        db_session.commit()
        return SimpleNamespace(id=task_id)

    dispatch_review_command(
        db_session,
        record.id,
        sender=sender,
        rollback_status="review_failed",
        error_message="dispatch failed",
    )
    db_session.refresh(record)
    assert record.status == "review_ready"


def test_broker_ack_loss_invalidates_published_generation(db_session, rows):
    _, _, record, _, _ = rows
    captured = {}

    def sender(record_id, **kwargs):
        captured.update(kwargs)
        raise ConnectionError("accepted but response lost")

    with pytest.raises(ConnectionError):
        dispatch_review_command(
            db_session,
            record.id,
            sender=sender,
            rollback_status="review_failed",
            error_message="unknown",
        )
    assert record.status == "review_failed"
    with review_scope(record.id, captured["review_generation"]):
        with pytest.raises(ReviewSuperseded):
            lock_record(db_session, record.id)


def test_corrected_mock_shells_are_reused_not_overwritten_from_chat(
    db_session, rows, monkeypatch
):
    user, _, record, qa, _ = rows
    edit_qa(
        db_session,
        record_id=record.id,
        qa_id=qa.id,
        current_user=user,
        payload=QAEditRequest(expected_version=1, answer="当前唯一有效回答"),
    )
    module = import_module("app.interviews.application.analysis_orchestrator")

    class NoClose:
        def __getattr__(self, name):
            return getattr(db_session, name)

        def close(self):
            pass

    monkeypatch.setattr(module, "SessionLocal", lambda: NoClose())
    result = module.analysis_orchestrator._load_existing_qa_shells(record.id)
    assert result[0]["answer"] == "当前唯一有效回答"
    assert result[0]["source_version"] == 2


def test_committed_success_is_not_rewound_after_broker_ack_loss(db_session, rows):
    _, _, record, _, _ = rows

    def sender(record_id, *, task_id, review_generation):
        current = db_session.get(InterviewRecord, record_id)
        current.status = "review_ready"
        current.analysis_json = '{"overall":{"score":8}}'
        db_session.commit()
        raise ConnectionError("broker reply lost after successful worker commit")

    receipt = dispatch_review_command(
        db_session,
        record.id,
        sender=sender,
        rollback_status="review_failed",
        error_message="unknown",
    )
    assert receipt.id == record.celery_task_id
    assert record.status == "review_ready"
    assert json.loads(record.analysis_json)["overall"]["score"] == 8


def test_analysis_maps_ids_not_positions_and_rejects_changed_input(
    db_session, rows, monkeypatch
):
    _, _, record, qa, sibling = rows
    module = import_module("app.interviews.application.analysis_orchestrator")

    class Borrowed:
        def __getattr__(self, name):
            return getattr(db_session, name)

        def close(self):
            pass

    monkeypatch.setattr(module, "SessionLocal", Borrowed)
    # A legacy blank QA need not occupy a scored-result position.
    qa.question = ""
    sibling.order_idx = 8
    db_session.commit()
    result = {
        "per_question": [
            {
                "qa_id": sibling.id,
                "source_version": 1,
                "score": 7,
                "criteria": [],
                "competency_evidence": [],
            }
        ]
    }
    module.analysis_orchestrator._persist_analysis(record.id, result)
    assert sibling.score == 7 and sibling.version == 2
    assert qa.version == 1
    with pytest.raises(ReviewSuperseded):
        module.analysis_orchestrator._persist_analysis(record.id, result)


def test_late_kb_publication_cannot_reactivate_corrected_answer(
    db_session, rows, monkeypatch
):
    import asyncio
    from app.rag.application.library.qa_publish_service import save_qa_to_knowledge
    from app.models.knowledge import KnowledgeDocument

    user, _, record, qa, _ = rows

    async def index_then_correct(**kw):
        edit_qa(
            db_session,
            record_id=record.id,
            qa_id=qa.id,
            current_user=user,
            payload=QAEditRequest(
                expected_version=qa.version, answer="纠正发生在索引期间"
            ),
        )
        return {"indexed": True, "chunk_count": 1}

    monkeypatch.setattr("app.rag.ingest.pipeline.ingest_text", index_then_correct)
    with pytest.raises(CommandError) as error:
        asyncio.run(
            save_qa_to_knowledge(db_session, user_pk=user.id, qa=qa, record=record)
        )
    assert error.value.kind == "conflict"
    old = db_session.query(KnowledgeDocument).one()
    assert old.status == "stale"
    # Explicitly saved new answer gets a new document identity. Old queued jobs
    # cannot replace its chunks through the previous document ID.
    qa.improved_answer = "基于当前纠正的改进回答"
    db_session.commit()

    async def index_current(**kw):
        return {"indexed": True, "chunk_count": 1}

    monkeypatch.setattr("app.rag.ingest.pipeline.ingest_text", index_current)
    current = asyncio.run(
        save_qa_to_knowledge(db_session, user_pk=user.id, qa=qa, record=record)
    )
    assert current.id != old.id and current.status == "ready"
    db_session.refresh(old)
    assert old.status == "stale"
