"""Wire-format contracts shared by the mock API and frontend types."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.chat import (
    MockAnswerRequest,
    MockAnswerResp,
    MockLiveStateResp,
    MockStartRequest,
    MockStartResp,
)


_MESSAGE = {
    "id": 42,
    "speaker": "interviewer",
    "text": "好的。能讲讲你最近做的一个项目吗？",
}


def test_mock_start_request_defaults_to_twenty_questions():
    base = {"resume_id": "rsm_1", "jd_text": "这是满足长度要求的后端工程师岗位说明文本"}
    assert MockStartRequest(**base).target_question_count == 20
    assert MockStartRequest(**base, target_question_count=30).target_question_count == 30
    with pytest.raises(ValidationError):
        MockStartRequest(**base, target_question_count=25)


def test_mock_start_request_requires_resume_and_meaningful_jd():
    with pytest.raises(ValidationError):
        MockStartRequest(jd_text="这是满足长度要求的后端工程师岗位说明文本")
    with pytest.raises(ValidationError):
        MockStartRequest(resume_id="rsm_1", jd_text="太短")
    with pytest.raises(ValidationError):
        MockStartRequest(resume_id="   ", jd_text="这是满足长度要求的后端工程师岗位说明文本")


def test_mock_answer_request_requires_concurrency_token():
    with pytest.raises(ValidationError):
        MockAnswerRequest(answer_text="回答")
    request = MockAnswerRequest(answer_text="回答", question_message_id=42)
    assert request.question_message_id == 42


def test_mock_answer_response_contains_only_live_ui_fields():
    response = MockAnswerResp(message=_MESSAGE, end_suggested=False)
    assert response.model_dump() == {
        "message": _MESSAGE,
        "end_suggested": False,
    }


def test_mock_start_response_contains_only_record_and_opening_message():
    response = MockStartResp(record_id="ir_x", message=_MESSAGE)
    assert response.model_dump() == {"record_id": "ir_x", "message": _MESSAGE}


def test_mock_live_state_accepts_complete_conversation():
    state = MockLiveStateResp(
        messages=[
            _MESSAGE,
            {"id": 43, "speaker": "candidate", "text": "我的回答"},
        ]
    )
    assert [message.speaker for message in state.messages] == [
        "interviewer",
        "candidate",
    ]
