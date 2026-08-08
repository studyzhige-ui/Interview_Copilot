from __future__ import annotations

from typing import Any

import pytest
from app.services.interview.mock_interview_service import NextTurn

from evaluation.mock_interview_eval import (
    DEFAULT_TRAJECTORY_DATASET,
    JUDGE_DIMENSIONS,
    _evaluate_trajectory,
    _expected_language,
    _language_matches,
    _load_cases,
)


async def _perfect_judge(*args) -> dict[str, Any]:
    return {**{dimension: 5 for dimension in JUDGE_DIMENSIONS}, "reason": "ok"}


class DeterministicInterviewer:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(
        self,
        *,
        stages,
        current_stage_key,
        user_answer,
        questions_in_current_stage,
        **kwargs,
    ) -> NextTurn:
        self.calls += 1
        keys = [stage["key"] for stage in stages]
        index = keys.index(current_stage_key)
        maximum = int(stages[index]["max_questions"])
        if questions_in_current_stage >= maximum:
            if index == len(keys) - 1:
                return NextTurn(
                    interviewer_message="感谢你的参与，本次模拟面试到这里结束。",
                    next_stage_key=current_stage_key,
                    is_ready_to_finish=True,
                )
            next_stage = keys[index + 1]
        else:
            next_stage = current_stage_key
        return NextTurn(
            interviewer_message=f"关于“{user_answer[:18]}”，请说明一个新的验证依据？",
            next_stage_key=next_stage,
            is_ready_to_finish=False,
        )


def test_trajectory_dataset_covers_release_scenarios() -> None:
    ids = {case["id"] for case in _load_cases(DEFAULT_TRAJECTORY_DATASET)}
    assert ids == {
        "complete-general-interview",
        "repeat-resistance-trajectory",
        "candidate-question-and-close",
        "off-topic-recovery",
        "bilingual-dialogue",
        "client-disconnect-resume",
    }


@pytest.mark.asyncio
async def test_complete_trajectory_visits_every_stage_and_finishes() -> None:
    case = next(
        case
        for case in _load_cases(DEFAULT_TRAJECTORY_DATASET)
        if case["id"] == "complete-general-interview"
    )
    generator = DeterministicInterviewer()

    result = await _evaluate_trajectory(
        case,
        "eval-user",
        turn_generator=generator,
        judge_turn=_perfect_judge,
    )

    assert result["passed"] is True
    assert result["visited_stages"] == case["required_stages"]
    assert result["turns"] == 13
    assert generator.calls == 13


@pytest.mark.asyncio
async def test_disconnect_recovery_does_not_generate_the_same_turn_twice() -> None:
    case = next(
        case
        for case in _load_cases(DEFAULT_TRAJECTORY_DATASET)
        if case["id"] == "client-disconnect-resume"
    )
    generator = DeterministicInterviewer()

    result = await _evaluate_trajectory(
        case,
        "eval-user",
        turn_generator=generator,
        judge_turn=_perfect_judge,
    )

    assert result["passed"] is True
    assert result["recovered_disconnects"] == 1
    assert generator.calls == result["turns"] == 3


def test_language_gate_distinguishes_zh_en_and_mixed() -> None:
    assert _language_matches("zh", "好的，请继续说明你的方案。")
    assert _language_matches("en", "Please explain the main engineering tradeoff.")
    assert _language_matches("mixed", "好的，请解释 Redis failover 的取舍。")
    assert not _language_matches("en", "请继续说明你的方案。")
    assert _expected_language("联合索引包含 user_id、status 和 created_at。") == "zh"
    assert _expected_language("我们使用 request coalescing and jittered TTL。") == "zh"
