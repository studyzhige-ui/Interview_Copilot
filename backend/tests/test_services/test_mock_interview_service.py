import asyncio
import json


def test_plan_parsing():
    from app.services.mock_interview_service import MockInterviewService

    service = MockInterviewService()

    raw = json.dumps({
        "phases": [
            {
                "phase_id": "self_intro",
                "phase_name": "自我介绍",
                "questions": [
                    {"question": "请介绍一下你自己。"}
                ]
            },
            {
                "phase_id": "technical",
                "phase_name": "技术基础",
                "questions": [
                    {"question": "什么是 HTTP?"},
                    {"question": "数据库索引原理?"},
                ]
            }
        ]
    })
    plan = service._parse_plan(raw)
    assert len(plan["phases"]) == 2
    assert plan["phases"][0]["phase_id"] == "self_intro"
    assert len(plan["phases"][1]["questions"]) == 2


def test_plan_parsing_with_code_fence():
    from app.services.mock_interview_service import MockInterviewService

    service = MockInterviewService()
    raw = '```json\n{"phases": [{"phase_id": "x", "phase_name": "X", "questions": [{"question": "q1"}]}]}\n```'
    plan = service._parse_plan(raw)
    assert len(plan["phases"]) == 1


def test_plan_parsing_invalid():
    from app.services.mock_interview_service import MockInterviewService

    service = MockInterviewService()
    plan = service._parse_plan('{"no_phases": true}')
    assert plan == {"phases": []}


def test_get_current_question_first():
    from app.services.mock_interview_service import MockInterviewService

    service = MockInterviewService()
    plan = {
        "phases": [
            {"phase_id": "intro", "phase_name": "自我介绍", "questions": [{"question": "q1"}]},
            {"phase_id": "tech", "phase_name": "技术", "questions": [{"question": "q2"}]},
        ]
    }
    state = {"current_phase": "", "current_question_idx": 0}
    result = service.get_current_question(state, plan)
    assert result["done"] is False
    assert result["phase_id"] == "intro"
    assert result["question"] == "q1"


def test_get_current_question_phase_transition():
    from app.services.mock_interview_service import MockInterviewService

    service = MockInterviewService()
    plan = {
        "phases": [
            {"phase_id": "intro", "phase_name": "自我介绍", "questions": [{"question": "q1"}]},
            {"phase_id": "tech", "phase_name": "技术", "questions": [{"question": "q2"}]},
        ]
    }
    state = {"current_phase": "intro", "current_question_idx": 1}
    result = service.get_current_question(state, plan)
    assert result["phase_id"] == "tech"
    assert result["question"] == "q2"


def test_get_current_question_done():
    from app.services.mock_interview_service import MockInterviewService

    service = MockInterviewService()
    plan = {
        "phases": [
            {"phase_id": "intro", "phase_name": "自我介绍", "questions": [{"question": "q1"}]},
        ]
    }
    state = {"current_phase": "intro", "current_question_idx": 1}
    result = service.get_current_question(state, plan)
    assert result["done"] is True


def test_advance_state_next_question():
    from app.services.mock_interview_service import MockInterviewService

    service = MockInterviewService()
    plan = {
        "phases": [
            {"phase_id": "tech", "phase_name": "技术", "questions": [
                {"question": "q1"},
                {"question": "q2"},
            ]},
        ]
    }
    state = {"current_phase": "tech", "current_question_idx": 0, "qa_history": []}

    interviewer_result = {
        "response": "好的，下一题。",
        "action": "next_question",
        "follow_up_question": "",
    }
    new_state = service.advance_state(state, plan, interviewer_result)
    assert new_state["current_question_idx"] == 1
    assert not new_state.get("is_finished")


def test_advance_state_follow_up():
    from app.services.mock_interview_service import MockInterviewService

    service = MockInterviewService()
    plan = {
        "phases": [
            {"phase_id": "tech", "phase_name": "技术", "questions": [
                {"question": "q1"},
                {"question": "q2"},
            ]},
        ]
    }
    state = {"current_phase": "tech", "current_question_idx": 0, "qa_history": []}

    interviewer_result = {
        "response": "能详细说说吗？",
        "action": "follow_up",
        "follow_up_question": "你提到了缓存，具体用了什么策略？",
    }
    new_state = service.advance_state(state, plan, interviewer_result)
    # Should advance to the follow-up (inserted at index 1)
    assert new_state["current_question_idx"] == 1
    # The follow-up should be inserted into the questions list
    assert len(plan["phases"][0]["questions"]) == 3
    assert plan["phases"][0]["questions"][1]["question"] == "你提到了缓存，具体用了什么策略？"


def test_advance_state_phase_transition():
    from app.services.mock_interview_service import MockInterviewService

    service = MockInterviewService()
    plan = {
        "phases": [
            {"phase_id": "intro", "phase_name": "自我介绍", "questions": [{"question": "q1"}]},
            {"phase_id": "tech", "phase_name": "技术", "questions": [{"question": "q2"}]},
        ]
    }
    state = {"current_phase": "intro", "current_question_idx": 0, "qa_history": []}

    interviewer_result = {
        "response": "好的，我们进入下一个环节。",
        "action": "next_question",
        "follow_up_question": "",
    }
    new_state = service.advance_state(state, plan, interviewer_result)
    assert new_state["current_phase"] == "tech"
    assert new_state["current_question_idx"] == 0


def test_advance_state_finished():
    from app.services.mock_interview_service import MockInterviewService

    service = MockInterviewService()
    plan = {
        "phases": [
            {"phase_id": "intro", "phase_name": "自我介绍", "questions": [{"question": "q1"}]},
        ]
    }
    state = {"current_phase": "intro", "current_question_idx": 0, "qa_history": []}

    interviewer_result = {"response": "谢谢", "action": "next_question", "follow_up_question": ""}
    new_state = service.advance_state(state, plan, interviewer_result)
    assert new_state.get("is_finished") is True


def test_fallback_plan():
    from app.services.mock_interview_service import MockInterviewService

    service = MockInterviewService()
    plan = service._fallback_plan()
    assert len(plan["phases"]) == 4
    assert plan["phases"][0]["phase_id"] == "self_intro"


def test_generate_plan_mocked():
    """Test generate_plan with a mocked LLM response."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from app.services.mock_interview_service import MockInterviewService

    service = MockInterviewService()
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "phases": [
            {"phase_id": "self_intro", "phase_name": "自我介绍",
             "questions": [{"question": "请介绍你自己"}]},
        ]
    })

    with patch("app.services.mock_interview_service.agent_fast_llm") as mock_llm:
        mock_llm.acomplete = AsyncMock(return_value=mock_response)
        plan = asyncio.run(
            service.generate_plan("Python 开发工程师简历")
        )

    assert plan["phases"][0]["phase_id"] == "self_intro"


def test_generate_interviewer_response_mocked():
    """Test generate_interviewer_response with a mocked LLM."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from app.services.mock_interview_service import MockInterviewService

    service = MockInterviewService()
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "response": "嗯，了解。那你能详细说说你在这个项目中的角色吗？",
        "action": "follow_up",
        "follow_up_question": "你在项目中负责哪些模块？",
    })

    with patch("app.services.mock_interview_service.agent_fast_llm") as mock_llm:
        mock_llm.acomplete = AsyncMock(return_value=mock_response)
        result = asyncio.run(
            service.generate_interviewer_response(
                question="请介绍你最近的项目",
                answer="我做了一个推荐系统",
                phase_id="resume_deep_dive",
            )
        )

    assert result["action"] == "follow_up"
    assert "角色" in result["response"]
    assert result["follow_up_question"] != ""


# batch_evaluate removed — analysis now happens asynchronously via
# InterviewAnalysisOrchestrator (see test_analysis_orchestrator.py).
