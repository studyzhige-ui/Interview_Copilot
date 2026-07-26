"""Phase 5 mock-flow behaviors: concurrency token (MOCK-3), two-phase
transaction dedupe (MOCK-4), rules-layer hard cap (MOCK-5), asked-question
inventory (MOCK-6), stage meta + audio in review pairing (MOCK-7/8)."""

from __future__ import annotations

import asyncio
import json
import sys

import pytest

from app.models.chat import Conversation
from app.services.interview import (
    mock_flow,
    mock_interview_service,
    mock_runtime_service,
)
from app.services.interview.interview_record_service import (
    STATUS_MOCK_IN_PROGRESS,
    interview_record_service,
)


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
        interview_plan=json.dumps(
            {"stages": mock_interview_service.GENERAL_PLAN_TEMPLATE}
        ),
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
        plan=mock_interview_service.GENERAL_PLAN_TEMPLATE,
        conversation_id=conv.id,
    )
    mock_runtime_service.advance_runtime(
        db,
        runtime,
        current_stage_key="self_intro",
        stage_index=0,
        current_question_text="你好，请自我介绍。",
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
    # No token / matching token both pass.
    turn = asyncio.run(
        mock_flow.submit_answer(
            db_session,
            record=record,
            runtime=runtime,
            answer_text="回答",
            answer_audio_file_asset_id=None,
            question_message_id=None,
        )
    )
    assert turn.question_message_id == runtime.current_question_message_id


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
            )
        )
    # Phase A committed the answer even though phase B failed.
    assert mock_flow.count_answered_turns(db_session, conv.id) == 1

    _stub_turn(monkeypatch)
    asyncio.run(
        mock_flow.submit_answer(
            db_session,
            record=record,
            runtime=runtime,
            answer_text="我的回答",
            answer_audio_file_asset_id=None,
        )
    )
    assert mock_flow.count_answered_turns(db_session, conv.id) == 1  # deduped


def test_hard_cap_forces_ready_to_finish(db_session, monkeypatch):
    record, runtime, conv = _make_run(db_session)
    _stub_turn(monkeypatch)
    monkeypatch.setattr(mock_flow, "MOCK_MAX_ANSWERED_TURNS", 1)
    turn = asyncio.run(
        mock_flow.submit_answer(
            db_session,
            record=record,
            runtime=runtime,
            answer_text="第一答",
            answer_audio_file_asset_id=None,
        )
    )
    assert turn.is_ready_to_finish is True  # rules layer overrode the LLM


def test_asked_questions_fed_to_prompt(db_session, monkeypatch):
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
        )
    )
    assert captured["asked_questions"] == ["你好，请自我介绍。"]
    assert captured["questions_in_current_stage"] == 1


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
    import app.services.interview.analysis_orchestrator  # noqa: F401

    orch = sys.modules["app.services.interview.analysis_orchestrator"]

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
