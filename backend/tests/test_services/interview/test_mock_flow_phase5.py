"""Mock-flow concurrency, recovery, length warning and review metadata."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime

import pytest
from app.models.chat import Conversation
from app.interviews.application import mock_flow
from app.interviews.application import mock_interview_service
from app.interviews.application import mock_runtime_service
from app.interviews.application.interview_record_service import STATUS_MOCK_IN_PROGRESS
from app.interviews.application.interview_record_service import interview_record_service


@pytest.fixture(autouse=True)
def _seed_user(db_session):
    from app.models.user import User

    db_session.add(User(username="alice", hashed_password="x"))
    db_session.flush()


def _pk(db):
    from app.models.user import User

    return db.query(User.id).filter(User.username == "alice").scalar()


def _make_run(db):
    """Record + conversation + opening message + runtime, like start_mock."""
    record = interview_record_service.create_for_mock(
        user_id="alice",
        title="模拟面试",
        db=db,
    )
    record.status = STATUS_MOCK_IN_PROGRESS
    conv = Conversation(
        id="conv_p5",
        user_id=_pk(db),
        title="模拟面试",
        type="mock_interview",
        mode="chat",
        subject_type="interview_record",
        subject_id=record.id,
    )
    db.add(conv)
    db.flush()
    opening = mock_flow.append_message(
        db,
        conv.id,
        "assistant",
        "你好，请自我介绍。",
        content_blocks_json=json.dumps([{"type": "stage", "stage_key": "self_intro"}]),
    )
    runtime = mock_runtime_service.create_runtime(
        db,
        user_id="alice",
        interview_record_id=record.id,
        plan=mock_interview_service.BASE_INTERVIEW_STAGES,
        conversation_id=conv.id,
        interviewer_style="professional",
        target_question_count=20,
        current_stage_key="self_intro",
        current_question_message_id=opening.id,
    )
    db.commit()
    return record, runtime, conv


def _stub_turn(monkeypatch, message="下一个问题？", stage="self_intro", captured=None):
    async def _fake(**kwargs):
        if captured is not None:
            captured.update(kwargs)
        return mock_interview_service.NextTurn(
            interviewer_message=message,
            next_stage_key=stage,
            is_ready_to_finish=False,
        )

    monkeypatch.setattr(mock_flow.mock_interview_service, "generate_next_turn", _fake)


def test_stale_question_token_rejected(db_session, monkeypatch):
    record, runtime, conv = _make_run(db_session)
    _stub_turn(monkeypatch)
    with pytest.raises(mock_flow.StaleQuestionError):
        asyncio.run(
            mock_flow.submit_answer(
                db_session,
                record=record,
                runtime=runtime,
                answer_text="回答",
                answer_audio_file_asset_id=None,
                question_message_id=runtime.current_question_message_id + 999,
            )
        )
    # A matching token advances the interview.
    turn = asyncio.run(
        mock_flow.submit_answer(
            db_session,
            record=record,
            runtime=runtime,
            answer_text="回答",
            answer_audio_file_asset_id=None,
            question_message_id=runtime.current_question_message_id,
        )
    )
    assert turn.question_message_id == runtime.current_question_message_id


def test_question_claim_rejects_overlapping_generation(db_session, monkeypatch):
    record, runtime, conv = _make_run(db_session)
    _stub_turn(monkeypatch)
    runtime.answer_claimed_at = datetime.now(UTC)
    db_session.commit()

    with pytest.raises(mock_flow.QuestionBusyError):
        asyncio.run(
            mock_flow.submit_answer(
                db_session,
                record=record,
                runtime=runtime,
                answer_text="重复提交",
                answer_audio_file_asset_id=None,
                question_message_id=runtime.current_question_message_id,
            )
        )

    assert mock_flow.count_answered_turns(db_session, conv.id) == 0


def test_dangling_answer_retry_not_double_recorded(db_session, monkeypatch):
    """MOCK-4: phase A persists the answer; if the LLM turn then fails, a
    retry with the same text must not append a second copy."""
    record, runtime, conv = _make_run(db_session)

    async def _boom(**kwargs):
        raise RuntimeError("LLM down")

    monkeypatch.setattr(mock_flow.mock_interview_service, "generate_next_turn", _boom)
    with pytest.raises(RuntimeError):
        asyncio.run(
            mock_flow.submit_answer(
                db_session,
                record=record,
                runtime=runtime,
                answer_text="我的回答",
                answer_audio_file_asset_id=None,
                question_message_id=runtime.current_question_message_id,
            )
        )
    # Phase A committed the answer even though phase B failed.
    assert mock_flow.count_answered_turns(db_session, conv.id) == 1
    db_session.refresh(runtime)
    assert runtime.answer_claimed_at is None

    _stub_turn(monkeypatch)
    asyncio.run(
        mock_flow.submit_answer(
            db_session,
            record=record,
            runtime=runtime,
            answer_text="我的回答",
            answer_audio_file_asset_id=None,
            question_message_id=runtime.current_question_message_id,
        )
    )
    assert mock_flow.count_answered_turns(db_session, conv.id) == 1  # deduped


def test_length_warning_is_fed_to_next_turn_without_forcing_finish(
    db_session, monkeypatch
):
    record, runtime, conv = _make_run(db_session)
    captured: dict = {}
    _stub_turn(monkeypatch, captured=captured)
    runtime.target_question_count = 1
    db_session.commit()
    turn = asyncio.run(
        mock_flow.submit_answer(
            db_session,
            record=record,
            runtime=runtime,
            answer_text="第一答",
            answer_audio_file_asset_id=None,
            question_message_id=runtime.current_question_message_id,
        )
    )
    assert captured["length_warning_active"] is True
    assert turn.is_ready_to_finish is False


def test_full_conversation_history_is_fed_to_prompt(db_session, monkeypatch):
    record, runtime, conv = _make_run(db_session)
    captured: dict = {}
    _stub_turn(monkeypatch, captured=captured)
    asyncio.run(
        mock_flow.submit_answer(
            db_session,
            record=record,
            runtime=runtime,
            answer_text="回答",
            answer_audio_file_asset_id=None,
            question_message_id=runtime.current_question_message_id,
        )
    )
    assert captured["conversation_messages"] == [
        {"role": "assistant", "content": "你好，请自我介绍。"}
    ]
    assert captured["length_warning_active"] is False


def test_review_pairing_reads_stage_and_audio(db_session, monkeypatch):
    """MOCK-7/8: the frozen QA pairs carry the real stage phase and the
    voice clip's asset id from the message content blocks."""
    record, runtime, conv = _make_run(db_session)
    mock_flow.append_message(
        db_session,
        conv.id,
        "user",
        "语音回答文本",
        content_blocks_json=json.dumps(
            [
                {"type": "text", "text": "语音回答文本"},
                {"type": "audio", "file_asset_id": "fa_clip_1"},
            ]
        ),
    )
    mock_flow.append_message(
        db_session,
        conv.id,
        "assistant",
        "讲讲你的项目难点？",
        content_blocks_json=json.dumps(
            [
                {"type": "stage", "stage_key": "resume_project_deep_dive"},
            ]
        ),
    )
    mock_flow.append_message(db_session, conv.id, "user", "文字回答")
    db_session.commit()

    # NB: the package __init__ re-exports the singleton under the module's
    # own name, so ``import ... as orch`` would bind the INSTANCE.
    import app.interviews.application.analysis_orchestrator  # noqa: F401

    orch = sys.modules["app.interviews.application.analysis_orchestrator"]

    class _NoClose:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def close(self):
            self._inner.commit()

    monkeypatch.setattr(orch, "SessionLocal", lambda: _NoClose(db_session))
    pairs = orch.analysis_orchestrator._load_mock_qa(record.id)

    assert len(pairs) == 2
    assert pairs[0]["phase"] == "self_intro"
    assert pairs[0]["answer_audio_file_asset_id"] == "fa_clip_1"
    assert pairs[0]["answer_input_mode"] == "voice"
    assert pairs[1]["phase"] == "resume_deep_dive"
    assert pairs[1]["answer_audio_file_asset_id"] is None
    assert pairs[1]["answer_input_mode"] == "text"


@pytest.mark.parametrize("outcome", ["success", "error", "cancel"])
def test_expired_owner_cannot_publish_or_release_successor(
    db_session, monkeypatch, outcome
):
    from datetime import timedelta
    from app.models.chat import ConversationMessage

    record, runtime, conv = _make_run(db_session)
    record_id, conversation_id = record.id, conv.id
    question_id = runtime.current_question_message_id
    captured = {}

    async def take_over(**kwargs):
        # Regression: count_answered_turns / expired ORM access after commit
        # used to reopen the connection throughout the slow model request.
        assert not db_session.in_transaction()
        current = mock_runtime_service.get_runtime_for_record(
            db_session, interview_record_id=record_id
        )
        first = current.answer_claim_generation
        current.answer_claimed_at = datetime.now(UTC) - timedelta(minutes=11)
        db_session.commit()
        assert (
            mock_runtime_service.claim_question(
                db_session, current, question_message_id=question_id
            )
            == "claimed"
        )
        captured["successor"] = current.answer_claim_generation
        assert captured["successor"] > first
        db_session.commit()
        if outcome == "error":
            raise RuntimeError("old model request failed")
        if outcome == "cancel":
            raise asyncio.CancelledError()
        return mock_interview_service.NextTurn("迟到的旧问题？", "self_intro", False)

    monkeypatch.setattr(mock_interview_service, "generate_next_turn", take_over)
    error = {
        "success": mock_flow.StaleQuestionError,
        "error": RuntimeError,
        "cancel": asyncio.CancelledError,
    }[outcome]
    with pytest.raises(error):
        asyncio.run(
            mock_flow.submit_answer(
                db_session,
                record=record,
                runtime=runtime,
                answer_text="唯一的原回答",
                answer_audio_file_asset_id=None,
                question_message_id=question_id,
            )
        )
    current = mock_runtime_service.get_runtime_for_record(
        db_session, interview_record_id=record_id
    )
    assert current.answer_claim_generation == captured["successor"]
    assert current.answer_claimed_at is not None
    assert current.current_question_message_id == question_id
    assert (
        db_session.query(ConversationMessage)
        .filter_by(conversation_id=conversation_id, role="assistant")
        .count()
        == 1
    )
    assert mock_flow.count_answered_turns(db_session, conversation_id) == 1


def test_model_result_cannot_extend_finished_interview(db_session, monkeypatch):
    record, runtime, conv = _make_run(db_session)
    record_id, conversation_id = record.id, conv.id
    question_id = runtime.current_question_message_id

    async def finished_during_generation(**kwargs):
        assert not db_session.in_transaction()
        current = mock_flow.get_owned_mock_record(db_session, record_id, "alice")
        current.status = "processing_review"
        db_session.commit()
        return mock_interview_service.NextTurn("不得写入的问题？", "self_intro", False)

    monkeypatch.setattr(
        mock_interview_service, "generate_next_turn", finished_during_generation
    )
    with pytest.raises(mock_flow.StaleQuestionError):
        asyncio.run(
            mock_flow.submit_answer(
                db_session,
                record=record,
                runtime=runtime,
                answer_text="保留这个回答",
                answer_audio_file_asset_id=None,
                question_message_id=question_id,
            )
        )
    assert len(mock_flow.conversation_messages(db_session, conversation_id)) == 2
    assert (
        mock_flow.get_owned_mock_record(db_session, record_id, "alice").status
        == "processing_review"
    )


def test_dangling_answer_cannot_be_replaced_without_an_explicit_revision(
    db_session, monkeypatch
):
    record, runtime, conv = _make_run(db_session)
    question_id = runtime.current_question_message_id

    async def fail(**_kwargs):
        raise RuntimeError("missing model response")

    monkeypatch.setattr(mock_flow.mock_interview_service, "generate_next_turn", fail)
    with pytest.raises(RuntimeError):
        asyncio.run(
            mock_flow.submit_answer(
                db_session,
                record=record,
                runtime=runtime,
                answer_text="original answer",
                answer_audio_file_asset_id=None,
                question_message_id=question_id,
            )
        )
    _stub_turn(monkeypatch)
    with pytest.raises(mock_flow.PendingAnswerConflictError):
        asyncio.run(
            mock_flow.submit_answer(
                db_session,
                record=record,
                runtime=runtime,
                answer_text="different answer",
                answer_audio_file_asset_id=None,
                question_message_id=question_id,
            )
        )
    db_session.rollback()
    messages = mock_flow.conversation_messages(db_session, conv.id)
    assert [
        message["content"] for message in messages if message["role"] == "user"
    ] == ["original answer"]
