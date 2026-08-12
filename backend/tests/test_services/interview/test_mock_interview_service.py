"""Unit tests for personalized mock planning and single-call turn generation."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.services.interview import mock_interview_service as mod
from app.services.interview.mock_interview_service import (
    BASE_INTERVIEW_STAGES,
    NextTurnGenerationError,
    build_prefix,
    detect_response_language,
    generate_next_turn,
    generate_plan,
    prefix_hash,
)


def test_build_prefix_is_deterministic():
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
    value = prefix_hash("anything")
    assert len(value) == 16
    assert prefix_hash("anything") == value


def test_response_language_follows_the_answer_not_technical_terms():
    assert detect_response_language("Python 是我最常用的后端语言。") == "zh"
    assert detect_response_language("联合索引包含 user_id 和 status。") == "zh"
    assert detect_response_language("We also added 熔断 and SLO alerts.") == "en"


def _plan_payload() -> dict:
    return {
        "guidance": {
            "self_intro": "围绕 Python 后端岗位判断整体匹配。",
            "resume_project_deep_dive": "深挖候选人的缓存平台项目和个人贡献。",
            "role_technical_assessment": "抽样考察 Redis、MySQL 和稳定性取舍，不做知识枚举。",
            "candidate_questions": "只根据 JD 回答团队问题，未知信息明确说明。",
        }
    }


def test_generate_plan_uses_resume_and_jd_to_personalize_guidance():
    response = MagicMock(text=json.dumps(_plan_payload(), ensure_ascii=False))
    with patch.object(mod, "get_llm_for_role") as factory:
        factory.return_value.complete.return_value = response
        plan = generate_plan(
            resume_context="负责 Redis 缓存平台",
            jd_context="Python 后端，要求 MySQL 与稳定性",
            interviewer_style="professional",
            user_id="alice",
        )

    prompt = factory.return_value.complete.call_args.args[0]
    assert "Redis 缓存平台" in prompt
    assert "Python 后端" in prompt
    assert [stage["key"] for stage in plan.stages] == [
        stage["key"] for stage in BASE_INTERVIEW_STAGES
    ]
    assert "缓存平台" in plan.stages[1]["guidance"]
    assert "自我介绍" in plan.opening_message


def test_generate_plan_opening_varies_by_style_formality():
    response = MagicMock(text=json.dumps(_plan_payload(), ensure_ascii=False))
    with patch.object(mod, "get_llm_for_role") as factory:
        factory.return_value.complete.return_value = response
        casual = generate_plan(interviewer_style="friendly").opening_message
        formal = generate_plan(interviewer_style="pressure").opening_message
    assert casual.startswith("你好")
    assert formal.startswith("您好")


def test_generate_plan_rejects_incomplete_guidance():
    response = MagicMock(text=json.dumps({"guidance": {"self_intro": "x"}}))
    with patch.object(mod, "get_llm_for_role") as factory:
        factory.return_value.complete.return_value = response
        with pytest.raises(ValueError, match="missing stage"):
            generate_plan()


def _stages():
    return [dict(stage) for stage in BASE_INTERVIEW_STAGES]


def test_generate_next_turn_uses_full_history_and_length_warning():
    response = MagicMock(
        text=json.dumps(
            {
                "message": "好的。能讲讲你最近的项目吗？",
                "next_stage_key": "resume_project_deep_dive",
                "ready_to_finish": False,
            }
        )
    )
    history = [
        {"role": "assistant", "content": "最早的问题"},
        {"role": "user", "content": "最早的回答"},
        *[{"role": "assistant", "content": f"后续问题 {index}"} for index in range(10)],
    ]
    with patch.object(mod, "get_llm_for_role") as factory:
        factory.return_value.acomplete = AsyncMock(return_value=response)
        turn = asyncio.run(
            generate_next_turn(
                prefix="P",
                stages=_stages(),
                current_stage_key="self_intro",
                conversation_messages=history,
                user_answer="我是候选人",
                length_warning_active=True,
            )
        )

    prompt = factory.return_value.acomplete.await_args.args[0]
    assert "最早的问题" in prompt
    assert "后续问题 9" in prompt
    assert "length_warning_active: true" in prompt
    assert turn.next_stage_key == "resume_project_deep_dive"
    assert turn.is_ready_to_finish is False


def test_generate_next_turn_rejects_unknown_backward_and_jump_stages():
    async def run(proposed: str):
        response = MagicMock(
            text=json.dumps(
                {
                    "message": "继续",
                    "next_stage_key": proposed,
                    "ready_to_finish": False,
                }
            )
        )
        with patch.object(mod, "get_llm_for_role") as factory:
            factory.return_value.acomplete = AsyncMock(return_value=response)
            return await generate_next_turn(
                prefix="P",
                stages=_stages(),
                current_stage_key="resume_project_deep_dive",
                conversation_messages=[],
                user_answer="answer",
            )

    assert asyncio.run(run("made_up")).next_stage_key == "resume_project_deep_dive"
    assert asyncio.run(run("self_intro")).next_stage_key == "resume_project_deep_dive"
    assert (
        asyncio.run(run("candidate_questions")).next_stage_key
        == "resume_project_deep_dive"
    )
    assert (
        asyncio.run(run("role_technical_assessment")).next_stage_key
        == "role_technical_assessment"
    )


def test_generate_next_turn_only_finishes_after_candidate_questions_started():
    async def run(current_stage: str, proposed_stage: str, ready):
        response = MagicMock(
            text=json.dumps(
                {
                    "message": "谢谢参与。",
                    "next_stage_key": proposed_stage,
                    "ready_to_finish": ready,
                }
            )
        )
        with patch.object(mod, "get_llm_for_role") as factory:
            factory.return_value.acomplete = AsyncMock(return_value=response)
            return await generate_next_turn(
                prefix="P",
                stages=_stages(),
                current_stage_key=current_stage,
                conversation_messages=[],
                user_answer="answer",
            )

    entering = asyncio.run(
        run("role_technical_assessment", "candidate_questions", True)
    )
    assert entering.is_ready_to_finish is False
    assert (
        asyncio.run(
            run("candidate_questions", "candidate_questions", "false")
        ).is_ready_to_finish
        is False
    )
    assert (
        asyncio.run(
            run("candidate_questions", "candidate_questions", True)
        ).is_ready_to_finish
        is True
    )


def test_generate_next_turn_retries_then_surfaces_generation_failure():
    response = MagicMock(text="not json at all")
    with patch.object(mod, "get_llm_for_role") as factory:
        factory.return_value.acomplete = AsyncMock(return_value=response)
        with pytest.raises(NextTurnGenerationError):
            asyncio.run(
                generate_next_turn(
                    prefix="P",
                    stages=_stages(),
                    current_stage_key="self_intro",
                    conversation_messages=[],
                    user_answer="answer",
                )
            )
    assert factory.return_value.acomplete.await_count == 2


def test_generate_next_turn_retries_a_question_list_as_one_focus():
    responses = [
        MagicMock(
            text=json.dumps(
                {
                    "message": "为什么这样设计？如何恢复？怎样保证一致性？",
                    "next_stage_key": "self_intro",
                    "ready_to_finish": False,
                }
            )
        ),
        MagicMock(
            text=json.dumps(
                {
                    "message": "这项设计最关键的取舍是什么？",
                    "next_stage_key": "self_intro",
                    "ready_to_finish": False,
                }
            )
        ),
    ]
    with patch.object(mod, "get_llm_for_role") as factory:
        factory.return_value.acomplete = AsyncMock(side_effect=responses)
        turn = asyncio.run(
            generate_next_turn(
                prefix="P",
                stages=_stages(),
                current_stage_key="self_intro",
                conversation_messages=[],
                user_answer="answer",
            )
        )

    assert turn.interviewer_message == "这项设计最关键的取舍是什么？"
    assert factory.return_value.acomplete.await_count == 2
    retry_prompt = factory.return_value.acomplete.await_args_list[1].args[0]
    assert "retry_correction" in retry_prompt
