"""Wire-format contract tests for ``app.schemas.chat`` Pydantic models.

These pin the *shape* of responses the API ships to the frontend so a BE-only
rename or type drift trips at the test run, not in a user's browser.

The mock-interview DTOs are mirrored 1:1 by the TS interfaces in
``frontend/src/types/api.ts`` — until an OpenAPI-generated client lands, that
pair must be edited together.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.chat import MockAnswerResp, MockStage, MockStartResp


# ── MockAnswerResp ───────────────────────────────────────────────────────

_VALID_ANSWER_RESP = {
    "interviewer_message": "好的。能讲讲你最近做的一个项目吗？",
    "current_stage_key": "resume_project_deep_dive",
    "is_ready_to_finish": False,
}


def test_mock_answer_resp_accepts_full_valid_payload():
    resp = MockAnswerResp(**_VALID_ANSWER_RESP)
    assert resp.current_stage_key == "resume_project_deep_dive"
    assert resp.is_ready_to_finish is False


def test_mock_answer_resp_matches_endpoint_dict_shape():
    """The /answer endpoint returns exactly these three fields — round-trip
    through model_dump to guard against drift with the response_model."""
    resp = MockAnswerResp(**_VALID_ANSWER_RESP)
    assert resp.model_dump() == _VALID_ANSWER_RESP


@pytest.mark.parametrize("missing", [
    "interviewer_message", "current_stage_key", "is_ready_to_finish",
])
def test_mock_answer_resp_requires_all_fields(missing):
    payload = {k: v for k, v in _VALID_ANSWER_RESP.items() if k != missing}
    with pytest.raises(ValidationError):
        MockAnswerResp(**payload)


# ── MockStartResp / MockStage ────────────────────────────────────────────


def test_mock_start_resp_accepts_full_valid_payload():
    payload = {
        "interview_record_id": "ir_x",
        "conversation_id": "c_x",
        "runtime_id": "mir_x",
        "current_stage_key": "self_intro",
        "current_question": "你好，我们开始吧。先请你做一个简单的自我介绍。",
        "plan_phases": [
            {"key": "self_intro", "title": "自我介绍"},
            {"key": "candidate_questions", "title": "反问"},
        ],
    }
    resp = MockStartResp(**payload)
    assert resp.runtime_id == "mir_x"
    assert resp.plan_phases[0].key == "self_intro"
    assert resp.model_dump() == payload


@pytest.mark.parametrize("missing", ["key", "title"])
def test_mock_stage_requires_both_fields(missing):
    payload = {k: v for k, v in {"key": "self_intro", "title": "自我介绍"}.items() if k != missing}
    with pytest.raises(ValidationError):
        MockStage(**payload)
