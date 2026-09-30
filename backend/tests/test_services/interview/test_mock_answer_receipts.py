"""Same intent replays or stays unresolved; only a new explicit intent dispatches."""

import asyncio
from datetime import timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.db.types import utc_now
from app.interviews.application import mock_flow, mock_answer_receipts as receipts
from app.models.mock_answer_submission import MockAnswerSubmission
from app.models.user import User
from app.schemas.chat import MockAnswerRequest
from tests.test_services.interview.test_mock_flow_phase5 import _make_run, _stub_turn


@pytest.fixture
def run(db_session):
    db_session.add(User(username="alice", hashed_password="x"))
    db_session.flush()
    return _make_run(db_session)


def command(runtime, **extra):
    return dict(
        request_id=str(uuid4()),
        question_message_id=runtime.current_question_message_id,
        answer_text="已经保存的回答",
        answer_audio_file_asset_id=None,
        **extra,
    )


async def test_replay_returns_exact_committed_reply_even_after_runtime_is_removed(
    db_session, run, monkeypatch
):
    record, runtime, conv = run
    args = command(runtime)
    _stub_turn(monkeypatch)
    first = await mock_flow.submit_answer(
        db_session, record=record, runtime=runtime, **args
    )
    record.status = "completed"
    db_session.delete(runtime)
    db_session.commit()
    monkeypatch.setattr(
        mock_flow.mock_interview_service,
        "generate_next_turn",
        lambda **_: pytest.fail("redispatched"),
    )
    replay = await mock_flow.submit_answer(
        db_session, record=record, runtime=None, **args
    )
    assert replay == first
    receipt = receipts.read_receipt(db_session, record.id, args["request_id"])
    assert (
        receipt.status == "completed"
        and receipt.response.message.id == first.question_message_id
    )
    assert mock_flow.count_answered_turns(db_session, conv.id) == 1


async def test_same_id_changed_text_question_or_asset_is_always_a_conflict(
    db_session, run, monkeypatch
):
    record, runtime, _ = run
    args = command(runtime)
    _stub_turn(monkeypatch)
    await mock_flow.submit_answer(db_session, record=record, runtime=runtime, **args)
    for field, value in (
        ("answer_text", "另一回答"),
        ("question_message_id", 999),
        ("answer_audio_file_asset_id", "other"),
    ):
        with pytest.raises(receipts.AnswerRequestConflict):
            await mock_flow.submit_answer(
                db_session, record=record, runtime=runtime, **{**args, field: value}
            )
        db_session.rollback()


async def test_unknown_request_never_dispatches_again_but_explicit_new_intent_can(
    db_session, run, monkeypatch
):
    record, runtime, conv = run
    args = command(runtime)
    calls = []

    async def fail(**kwargs):
        assert not db_session.in_transaction()
        calls.append(kwargs)
        raise RuntimeError("response unknown")

    monkeypatch.setattr(mock_flow.mock_interview_service, "generate_next_turn", fail)
    with pytest.raises(RuntimeError, match="unknown"):
        await mock_flow.submit_answer(
            db_session, record=record, runtime=runtime, **args
        )
    assert (
        receipts.read_receipt(db_session, record.id, args["request_id"]).status
        == "unknown"
    )
    with pytest.raises(receipts.AnswerRequestUnresolved):
        await mock_flow.submit_answer(
            db_session, record=record, runtime=runtime, **args
        )
    db_session.rollback()
    assert len(calls) == 1
    _stub_turn(monkeypatch)
    await mock_flow.submit_answer(
        db_session,
        record=record,
        runtime=runtime,
        **{**args, "request_id": str(uuid4())},
    )
    assert mock_flow.count_answered_turns(db_session, conv.id) == 1
    assert (
        receipts.read_receipt(db_session, record.id, args["request_id"]).status
        == "unknown"
    )


async def test_same_inflight_id_is_fenced_and_read_only_expiry_never_releases_it(
    db_session, run, monkeypatch
):
    record, runtime, _ = run
    args = command(runtime)
    # Simulate a hard-killed process after the Phase A commit.
    receipts.start(db_session, record.id, MockAnswerRequest(**args), 1)
    row = db_session.query(MockAnswerSubmission).one()
    row.created_at = utc_now() - timedelta(
        seconds=receipts.ANSWER_CLAIM_TTL_SECONDS + 1
    )
    db_session.commit()
    assert (
        receipts.read_receipt(db_session, record.id, args["request_id"]).status
        == "unknown"
    )
    assert row.status == "in_progress"  # GET did not change the stored execution state.
    monkeypatch.setattr(
        mock_flow.mock_interview_service,
        "generate_next_turn",
        lambda **_: pytest.fail("redispatched"),
    )
    with pytest.raises(receipts.AnswerRequestUnresolved):
        await mock_flow.submit_answer(
            db_session, record=record, runtime=runtime, **args
        )


async def test_repeated_cancel_marks_unknown_and_releases_only_its_claim(
    db_session, run, monkeypatch
):
    record, runtime, _ = run
    args = command(runtime)

    async def cancel(**kwargs):
        raise asyncio.CancelledError

    monkeypatch.setattr(mock_flow.mock_interview_service, "generate_next_turn", cancel)
    with pytest.raises(asyncio.CancelledError):
        await mock_flow.submit_answer(
            db_session, record=record, runtime=runtime, **args
        )
    assert (
        receipts.read_receipt(db_session, record.id, args["request_id"]).status
        == "unknown"
    )
    db_session.refresh(runtime)
    assert runtime.answer_claimed_at is None


async def test_response_lost_after_commit_does_not_downgrade_valid_receipt(
    db_session, run, monkeypatch
):
    record, runtime, _ = run
    args = command(runtime)
    _stub_turn(monkeypatch)
    await mock_flow.submit_answer(db_session, record=record, runtime=runtime, **args)
    row = db_session.query(MockAnswerSubmission).one()
    receipts.mark_unknown(db_session, record.id, row.request_id, row.claim_generation)
    db_session.commit()
    assert (
        receipts.read_receipt(db_session, record.id, args["request_id"]).status
        == "completed"
    )


def test_command_contract_rejects_missing_uuid_coercions_blank_and_excess_input():
    valid = dict(request_id=str(uuid4()), question_message_id=1, answer_text="回答")
    for change in (
        {"request_id": "bad"},
        {"request_id": True},
        {"question_message_id": True},
        {"question_message_id": "1"},
        {"answer_text": " "},
        {"answer_text": "a" * 50_001},
    ):
        with pytest.raises(ValidationError):
            MockAnswerRequest(**{**valid, **change})
    with pytest.raises(ValidationError):
        MockAnswerRequest(answer_text="回答", question_message_id=1)
