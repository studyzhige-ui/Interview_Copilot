"""Purpose is a business contract shared by UI and Agent, not a new Agent loop."""

import json
from types import SimpleNamespace
from unittest.mock import Mock, AsyncMock
import pytest
from app.interviews.domain.specification import (
    InterviewSpecification,
    resolve_specification,
)
from app.schemas.mock_preparation import MockPreparationRequest
from app.agent_runtime.tools.mock_interview import StartMockInterviewArgs
from app.interviews.application.mock_interview_service import (
    generate_plan,
    generate_next_turn,
    build_prefix,
)


@pytest.mark.parametrize("contract", [MockPreparationRequest, StartMockInterviewArgs])
def test_targeted_practice_needs_only_a_goal(contract):
    command = contract(purpose="focused_practice", focus="Python协程取消")
    assert command.resume_id is None and command.jd_text is None
    assert command.input_mode == "text"
    with pytest.raises(ValueError):
        contract(purpose="focused_practice", focus=" ")
    with pytest.raises(ValueError):
        contract(purpose="project_deep_dive", focus="项目并发控制")
    assert (
        contract(
            purpose="project_deep_dive", focus="项目并发控制", resume_id="resume-1"
        ).jd_text
        is None
    )
    with pytest.raises(ValueError):
        contract(resume_id="resume-1")


@pytest.mark.parametrize(
    "purpose,focus,keys",
    [
        (
            "full",
            None,
            [
                "self_intro",
                "resume_project_deep_dive",
                "role_technical_assessment",
                "candidate_questions",
            ],
        ),
        ("project_deep_dive", "项目的并发控制", ["resume_project_deep_dive"]),
        ("focused_practice", "Python资源清理", ["role_technical_assessment"]),
    ],
)
def test_model_cannot_expand_the_selected_purpose(purpose, focus, keys):
    spec = InterviewSpecification(purpose=purpose, focus=focus)
    llm = SimpleNamespace(
        context_window=128000,
        max_tokens=4096,
        complete=Mock(
            return_value=SimpleNamespace(
                text=json.dumps(
                    {"guidance": {key: "考察具体依据及失败边界。" for key in keys}}
                )
            )
        ),
    )
    plan = generate_plan(specification=spec, llm=llm)
    assert [s["key"] for s in plan.stages] == keys
    assert plan.first_stage_key == keys[0]
    assert purpose in llm.complete.call_args.args[0]
    if purpose != "full":
        assert "自我介绍" not in plan.opening_message
        assert focus in plan.opening_message
    llm.complete.return_value.text = json.dumps(
        {"guidance": {**{key: "指导" for key in keys}, "invented_stage": "扩大范围"}}
    )
    with pytest.raises(ValueError, match="exactly"):
        generate_plan(specification=spec, llm=llm)


@pytest.mark.asyncio
async def test_single_stage_can_recommend_finish_without_inventing_candidate_questions():
    spec = InterviewSpecification(purpose="focused_practice", focus="事务与重试")
    llm = SimpleNamespace(
        context_window=128000,
        max_tokens=4096,
        acomplete=AsyncMock(
            return_value=SimpleNamespace(
                text=json.dumps(
                    {
                        "message": "本次目标已经讨论清楚，准备好后可以结束练习并生成复盘。",
                        "next_stage_key": "role_technical_assessment",
                        "ready_to_finish": True,
                    }
                )
            )
        ),
    )
    result = await generate_next_turn(
        prefix=build_prefix("", "", "professional", specification=spec),
        stages=[
            {
                "key": "role_technical_assessment",
                "title": "专项练习",
                "guidance": "讨论事务与重试",
            }
        ],
        current_stage_key="role_technical_assessment",
        conversation_messages=[],
        user_answer="已经回答完毕，可以结束。",
        llm=llm,
    )
    assert result.is_ready_to_finish
    assert result.next_stage_key == "role_technical_assessment"


def test_historical_records_have_an_explicit_full_flow_default():
    assert resolve_specification(None).purpose == "full"
    assert len(resolve_specification(None).stage_keys) == 4
