"""Tests for app.services.interview.mock_interview_service (target architecture).

The Runtime Director (run_director / validate_director / apply_state_update /
the 6 hard constraints / retry loop) was deleted in CONVERSATION-MOCK. The new
surface is:
  - build_prefix / prefix_hash   (deterministic cacheable prefix)
  - generate_plan                (freeze stages + opening line, no LLM)
  - stages_from_plan_json        (parse the frozen stage list back out)
  - generate_next_turn           (one LLM call per answer, no retry/validation)
"""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.interview import mock_interview_service as mod
from app.services.interview.mock_interview_service import (
    GENERAL_PLAN_TEMPLATE,
    NextTurn,
    build_prefix,
    generate_next_turn,
    generate_plan,
    prefix_hash,
    stages_from_plan_json,
)


# ── build_prefix / prefix_hash ───────────────────────────────────────────


def test_build_prefix_is_deterministic():
    """Same inputs → byte-identical prefix (DeepSeek prompt-cache stability)."""
    a = build_prefix("resume A", "jd A", "professional")
    b = build_prefix("resume A", "jd A", "professional")
    assert a == b
    assert "resume A" in a
    assert "jd A" in a


def test_build_prefix_falls_back_when_inputs_empty():
    prefix = build_prefix("", "", "professional")
    assert "未提供简历" in prefix
    assert "未提供 JD" in prefix


def test_prefix_hash_is_short_and_stable():
    h = prefix_hash("anything")
    assert isinstance(h, str)
    assert len(h) == 16
    assert prefix_hash("anything") == h


# ── generate_plan ────────────────────────────────────────────────────────


def test_generate_plan_freezes_general_template():
    plan = generate_plan(
        resume_context="r", jd_context="j", interviewer_style="professional",
        plan_template_key="general",
    )
    assert plan.template_key == "general"
    assert [s["key"] for s in plan.stages] == [s["key"] for s in GENERAL_PLAN_TEMPLATE]
    assert plan.first_stage_key == "self_intro"
    # Opening is deterministic + invites a self-introduction.
    assert "自我介绍" in plan.opening_message
    # plan_json round-trips through stages_from_plan_json.
    assert stages_from_plan_json(plan.plan_json) == plan.stages


def test_generate_plan_opening_varies_by_style_formality():
    casual = generate_plan(interviewer_style="friendly").opening_message
    formal = generate_plan(interviewer_style="pressure").opening_message
    assert casual.startswith("你好")
    assert formal.startswith("您好")


def test_unknown_template_falls_back_to_general():
    plan = generate_plan(plan_template_key="does_not_exist")
    assert [s["key"] for s in plan.stages] == [s["key"] for s in GENERAL_PLAN_TEMPLATE]


# ── stages_from_plan_json ────────────────────────────────────────────────


def test_stages_from_plan_json_parses_and_falls_back():
    good = json.dumps({"stages": [{"key": "a", "title": "甲"}, {"key": "b", "title": "乙"}]})
    assert stages_from_plan_json(good) == [
        {"key": "a", "title": "甲"}, {"key": "b", "title": "乙"},
    ]
    # Garbage / empty → the canonical general template.
    assert stages_from_plan_json("not json") == GENERAL_PLAN_TEMPLATE
    assert stages_from_plan_json(None) == GENERAL_PLAN_TEMPLATE
    assert stages_from_plan_json(json.dumps({"stages": []})) == GENERAL_PLAN_TEMPLATE


# ── generate_next_turn ───────────────────────────────────────────────────


def _stages():
    return [{"key": k, "title": k} for k in (
        "self_intro", "resume_project_deep_dive", "role_technical_assessment",
        "candidate_questions",
    )]


def test_generate_next_turn_parses_llm_output():
    resp = MagicMock()
    resp.text = json.dumps({
        "message": "好的。能讲讲你最近的项目吗？",
        "stage_key": "resume_project_deep_dive",
        "ready_to_finish": False,
    })
    with patch.object(mod, "_mock_llm") as mock_llm:
        mock_llm.acomplete = AsyncMock(return_value=resp)
        turn = asyncio.run(generate_next_turn(
            prefix="P", stages=_stages(), current_stage_key="self_intro",
            recent_messages=[{"role": "assistant", "content": "请自我介绍"}],
            user_answer="我是候选人",
        ))
    assert isinstance(turn, NextTurn)
    assert turn.interviewer_message.startswith("好的")
    assert turn.next_stage_key == "resume_project_deep_dive"
    assert turn.is_ready_to_finish is False
    assert mock_llm.acomplete.await_count == 1


def test_generate_next_turn_rejects_unknown_stage_key():
    """An LLM-hallucinated stage outside the plan keeps the current stage."""
    resp = MagicMock()
    resp.text = json.dumps({"message": "继续", "stage_key": "made_up", "ready_to_finish": False})
    with patch.object(mod, "_mock_llm") as mock_llm:
        mock_llm.acomplete = AsyncMock(return_value=resp)
        turn = asyncio.run(generate_next_turn(
            prefix="P", stages=_stages(), current_stage_key="role_technical_assessment",
            recent_messages=[], user_answer="answer",
        ))
    assert turn.next_stage_key == "role_technical_assessment"


def test_generate_next_turn_survives_parse_failure():
    """A garbage / failed LLM response must NOT raise — the interview keeps
    moving with a safe generic line and the current stage held."""
    resp = MagicMock()
    resp.text = "not json at all"
    with patch.object(mod, "_mock_llm") as mock_llm:
        mock_llm.acomplete = AsyncMock(return_value=resp)
        turn = asyncio.run(generate_next_turn(
            prefix="P", stages=_stages(), current_stage_key="self_intro",
            recent_messages=[], user_answer="answer",
        ))
    assert isinstance(turn, NextTurn)
    assert turn.interviewer_message  # non-empty fallback
    assert turn.next_stage_key == "self_intro"
    assert turn.is_ready_to_finish is False
