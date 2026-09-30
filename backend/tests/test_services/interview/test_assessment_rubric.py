import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from app.interviews.domain.assessment import (
    criteria_score,
    verify_competencies,
    aggregate_competencies,
    weights_for,
)
from app.interviews.application.analysis import service
from app.core.execution_errors import ModelOutcomeUnknownError


def source(**kwargs):
    return {
        "index": 1,
        "phase": "technical",
        "question": "如何控制并发?",
        "answer": "使用信号量限制并发，取消等待不等于任务结束。",
        **kwargs,
    }


def criteria(score=8):
    return [
        {"key": key, "score": score, "reason": "该回答有具体支持，但还缺少压测证据。"}
        for key in weights_for("technical")
    ]


def output(**kwargs):
    return {
        "results": [
            {
                "index": 1,
                "assessable": True,
                "criteria": criteria(),
                "critique": "说明了两个边界。",
                "improved_answer": "可以补充取消和资源回收的实现。",
                "tags": ["并发"],
                "competency_evidence": [],
                **kwargs,
            }
        ]
    }


def test_total_uses_one_ten_point_scale_and_declared_weights():
    values = criteria(10)
    values[0]["score"] = 5
    score, _ = criteria_score(values, source())
    assert score == 8  # correctness weight40%, other dimensions10
    parsed = service._validate_batch_result(output(criteria=values), [1], {1: source()})
    assert parsed[1]["score"] == 8


@pytest.mark.parametrize("bad", [True, "8", 11, -1, float("nan"), 8.25])
def test_invalid_criterion_not_coerced(bad):
    with pytest.raises(ValueError):
        criteria_score(criteria(bad), source())


def test_duplicate_and_missing_criteria_rejected():
    for rows in (criteria()[:-1], criteria() + [criteria()[0]]):
        with pytest.raises(ValueError):
            criteria_score(rows, source())


def test_model_cannot_supply_its_own_total_or_untyped_assessable():
    for value in (output(score=99), output(assessable="true")):
        with pytest.raises(ValueError):
            service._validate_batch_result(value, [1], {1: source()})


def test_api_keyword_and_phase_cannot_generate_coding_ability():
    q = source(
        question="API的英文全称是什么?",
        answer="Application programming interface",
        score=9,
        tags=["API", "Python"],
        phase="technical",
    )
    radar, evidence = aggregate_competencies([q])
    assert all(value is None for value in radar.values())
    assert all(value == [] for value in evidence.values())
    with pytest.raises(ValueError, match="verified coding"):
        verify_competencies(
            [
                {
                    "dimension": "编码能力",
                    "score": 9,
                    "answer_quote": q["answer"],
                    "reason": "出现API",
                }
            ],
            q,
        )


def test_dimension_requires_quote_from_this_answer_and_own_score():
    item = {
        "dimension": "系统设计",
        "score": 7,
        "answer_quote": "使用信号量限制并发",
        "reason": "区分了准入与取消，但缺少容量分析。",
    }
    q = source(score=9, competency_evidence=[item], qa_id="qa_one", source_version=3)
    radar, evidence = aggregate_competencies([q])
    assert radar["系统设计"] == 7 and radar["编码能力"] is None
    assert evidence["系统设计"][0]["source_version"] == 3
    with pytest.raises(ValueError, match="quote"):
        verify_competencies([{**item, "answer_quote": "我写出了可执行的代码"}], q)


def test_real_zero_and_unassessed_are_not_confused():
    result = service._validate_batch_result(
        output(criteria=criteria(0)), [1], {1: source()}
    )
    assert result[1]["score"] == 0
    result = service._validate_batch_result(
        output(assessable=False, criteria=[]), [1], {1: source(answer="")}
    )
    assert result[1]["score"] is None


def test_target_answer_is_not_silently_cut_at_1200_characters():
    answer = "技术内容" * 800 + "决定性末尾条件：必须等待底层任务释放资源。"
    rendered = service._render_qa_block(source(answer=answer), "test")
    assert answer in rendered


@pytest.mark.asyncio
async def test_unknown_response_never_triggers_batch_to_single_question_replay():
    llm = SimpleNamespace(
        acomplete=AsyncMock(
            side_effect=ModelOutcomeUnknownError("sent response unknown")
        )
    )
    with pytest.raises(ModelOutcomeUnknownError):
        await service._analyze_batch(
            [source()], [], [], resume_context="", jd_context="", llm=llm
        )
    assert llm.acomplete.await_count == 1


@pytest.mark.asyncio
async def test_valid_complete_assessment_carries_evidence(monkeypatch):
    llm = SimpleNamespace(
        acomplete=AsyncMock(
            return_value=SimpleNamespace(text=json.dumps(output(), ensure_ascii=False))
        )
    )
    result = await service._analyze_batch(
        [source(qa_id="qa-1", source_version=2)],
        [],
        [],
        resume_context="",
        jd_context="",
        llm=llm,
    )
    assert result[0]["score"] == 8 and len(result[0]["criteria"]) == 5
    assert result[0]["qa_id"] == "qa-1" and result[0]["source_version"] == 2
