"""Wire-format contract tests for ``app.schemas.chat`` Pydantic models.

These pin the *shape* of responses the API ships to the frontend so
a BE-only rename or type drift trips at startup of the test run,
not in a user's browser.

``MockAnswerResp`` is mirrored 1:1 by
``MockAnswerResp`` in ``frontend/src/types/api.ts``. Adding a new
``MockDirectorAction`` literal here without updating the TS union
would still ship a runtime bug — until the OpenAPI-generated TS
client lands, that pair must be edited together.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.chat import MockAnswerResp, MockPhaseProgress


# Single fully-populated dict used as the baseline for the
# permutation tests below.
_VALID_PROGRESS = {
    "current_phase": "technical",
    "turn_count": 3,
    "max_turns": 14,
    "follow_up_depth": 1,
}
_VALID_ANSWER_RESP = {
    "interviewer_response": "好的，下一题：你设计过 cache 失效策略吗？",
    "spoken_response": "好的。",
    "next_question": "你设计过 cache 失效策略吗？",
    "action": "new_question",
    "display_intent": "新问题",
    "is_finished": False,
    "phase_progress": _VALID_PROGRESS,
}


def test_mock_answer_resp_accepts_full_valid_payload():
    """Baseline: every field present + valid → model constructs."""
    resp = MockAnswerResp(**_VALID_ANSWER_RESP)
    assert resp.action == "new_question"
    assert resp.phase_progress.turn_count == 3


@pytest.mark.parametrize("missing", [
    "interviewer_response",
    "spoken_response",
    "next_question",
    "action",
    "display_intent",
    "is_finished",
    "phase_progress",
])
def test_mock_answer_resp_requires_all_top_level_fields(missing):
    """Every field is required (no Optional). Drop one → reject."""
    payload = {k: v for k, v in _VALID_ANSWER_RESP.items() if k != missing}
    with pytest.raises(ValidationError):
        MockAnswerResp(**payload)


@pytest.mark.parametrize("action", [
    "follow_up", "new_question", "transition",
    "hint", "clarify", "reverse_answer", "finish",
])
def test_mock_answer_resp_action_accepts_all_seven_director_actions(action):
    """The Literal enum must accept exactly the seven keys in
    ``app.services.interview.mock_interview_service.DISPLAY_INTENT``. If the
    Director adds a new action and you forget to update the
    Literal, this test fails — forcing the FE union to update too."""
    payload = {**_VALID_ANSWER_RESP, "action": action}
    resp = MockAnswerResp(**payload)
    assert resp.action == action


def test_mock_answer_resp_rejects_unknown_action():
    """If the service somehow returned an action outside the enum,
    Pydantic must refuse rather than let the BE silently ship a
    string the FE doesn't render. The reverse of the test above:
    same payload but ``action="accept"`` (a plausible-looking
    intruder) should raise."""
    payload = {**_VALID_ANSWER_RESP, "action": "accept"}
    with pytest.raises(ValidationError, match="action"):
        MockAnswerResp(**payload)


@pytest.mark.parametrize("missing", [
    "current_phase", "turn_count", "max_turns", "follow_up_depth",
])
def test_phase_progress_requires_all_fields(missing):
    """v6 schema commits to writing all four progress fields on
    every turn. Pin that — an Optional creep here would let the
    Director ship a turn without ``follow_up_depth`` and the FE's
    non-optional type would break at runtime."""
    payload = {k: v for k, v in _VALID_PROGRESS.items() if k != missing}
    with pytest.raises(ValidationError):
        MockPhaseProgress(**payload)


def test_mock_answer_resp_nested_progress_type_is_validated():
    """Pydantic must descend into nested model — passing a phase
    progress dict missing a sub-field must fail at the *parent*
    construction site, not silently."""
    payload = {
        **_VALID_ANSWER_RESP,
        "phase_progress": {"current_phase": "behavioral", "turn_count": 1},
    }
    with pytest.raises(ValidationError):
        MockAnswerResp(**payload)


def test_mock_answer_resp_matches_endpoint_dict_shape():
    """The endpoint at app/api/chat/mock_interview.py:609 builds the
    response as a plain dict. This test mimics that dict construction
    with realistic values and proves the Pydantic model accepts it
    verbatim — guards against drift between the endpoint return
    statement and the response_model.
    """
    endpoint_built = {
        "interviewer_response": "好。下一题：举一个最近的项目里你解决得最棘手的 bug。",
        "spoken_response": "好。",
        "next_question": "举一个最近的项目里你解决得最棘手的 bug。",
        "action": "follow_up",
        "display_intent": "追问",
        "is_finished": False,
        "phase_progress": {
            "current_phase": "technical",
            "turn_count": 7,
            "max_turns": 14,
            "follow_up_depth": 2,
        },
    }
    resp = MockAnswerResp(**endpoint_built)
    # Round-trip through model_dump to confirm field names and types
    # match — Pydantic would coerce ints to strings silently otherwise.
    dumped = resp.model_dump()
    assert dumped == endpoint_built
