from __future__ import annotations

import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from evaluation import mock_interview_eval as evaluator
from evaluation.llm_factory import EvaluationLLMConfig
from evaluation.mock_contracts import JUDGE_DIMENSIONS, JudgeResult
from evaluation.mock_run import (
    CallJournal,
    CampaignLimitError,
    MockJudgeClient,
    RecordedGenerator,
    write_report,
)


def valid_judge():
    return {**dict.fromkeys(JUDGE_DIMENSIONS, 10), "reason": "Evidence is supported."}


@pytest.mark.parametrize("bad", [99, 10.1, -1, "5", "99", 5.05, True, None, [], {}])
def test_invalid_judge_scores_are_not_coerced_or_clamped(bad):
    data = valid_judge()
    data["grounding"] = bad
    with pytest.raises(ValueError):
        evaluator._parse_json(json.dumps(data))


@pytest.mark.parametrize("patch", [{"reason": " "}, {"extra": 1}, {"relevance": None}])
def test_judge_requires_complete_documented_contract(patch):
    with pytest.raises(ValueError):
        JudgeResult.model_validate({**valid_judge(), **patch})


def test_valid_json_and_fences_are_supported():
    data = valid_judge()
    assert evaluator._parse_json("```json\n" + json.dumps(data) + "\n```") == data


@pytest.mark.parametrize(
    "payload", ['{"relevance": 10,"relevance": 1}', '{"relevance": NaN}', "[]"]
)
def test_ambiguous_and_nonfinite_json_fail(payload):
    with pytest.raises(ValueError):
        evaluator._parse_json(payload)


def args_for(tmp_path, mode="all"):
    return SimpleNamespace(
        mode=mode,
        case=None,
        user="eval-user",
        max_model_calls=256,
        turn_dataset=tmp_path / "turns.jsonl",
        trajectory_dataset=tmp_path / "trajectories.jsonl",
    )


def write_case(path, dataset):
    line = dataset.read_text().splitlines()[0]
    path.write_text(line + "\n", encoding="utf-8")


@pytest.mark.asyncio
async def test_all_selected_data_validated_before_first_paid_call(
    tmp_path, monkeypatch
):
    args = args_for(tmp_path)
    write_case(args.turn_dataset, evaluator.DEFAULT_TURN_DATASET)
    args.trajectory_dataset.write_text("")
    monkeypatch.setattr(
        evaluator, "get_llm_for_role", lambda *a, **k: pytest.fail("model resolved")
    )
    with pytest.raises(ValueError, match="no cases"):
        await evaluator._run(args)


def test_duplicate_ids_and_string_booleans_fail_preflight(tmp_path):
    path = tmp_path / "cases.jsonl"
    case = evaluator._load_cases(evaluator.DEFAULT_TURN_DATASET)[0]
    path.write_text((json.dumps(case) + "\n") * 2)
    with pytest.raises(ValueError, match="duplicate"):
        evaluator._load_cases(path)
    case["expect_finish"] = "false"
    path.write_text(json.dumps(case))
    with pytest.raises(ValueError, match="line 1"):
        evaluator._load_cases(path)


def test_cross_section_selection_and_explicit_empty_rejection(tmp_path):
    args = args_for(tmp_path)
    write_case(args.turn_dataset, evaluator.DEFAULT_TURN_DATASET)
    write_case(args.trajectory_dataset, evaluator.DEFAULT_TRAJECTORY_DATASET)
    args.case = ["self-intro-to-project", "complete-general-interview"]
    assert set(evaluator._prepare_cases(args)) == {"turns", "trajectories"}
    args.case = ["complete-general-interview"]
    with pytest.raises(ValueError, match="turns has no cases"):
        evaluator._prepare_cases(args)
    args.mode = "trajectory"
    assert list(evaluator._prepare_cases(args)) == ["trajectories"]


def sample_result():
    return {
        "passed": True,
        "judge": valid_judge(),
        "judge_mean": 10,
        "latency_ms": 20,
        "checks": {"valid_stage": True},
    }


def completed_report():
    return {
        "schema_version": 3,
        "score_scale": {
            "version": "score10-v1",
            "range": [0, 10],
            "precision": 1,
            "missing": "unknown_not_zero",
        },
        "status": "completed",
        "requested_sections": ["turns"],
        "turns": evaluator._aggregate_turns([sample_result()]),
        "trajectories": {
            "status": "not_run",
            "samples": 0,
            "pass_rate": None,
            "details": [],
        },
    }


def test_gate_requires_samples_and_selected_completion():
    report = completed_report()
    assert evaluator._passes_gate(report)
    report["turns"] = evaluator._aggregate_turns([])
    assert report["turns"]["pass_rate"] is None
    assert not evaluator._passes_gate(report)
    assert not evaluator._passes_gate(
        {"turns": {"samples": 0}, "trajectories": {"samples": 0}}
    )
    report = completed_report()
    report["requested_sections"].append("trajectories")
    assert not evaluator._passes_gate(report)
    report = completed_report()
    report["status"] = "running"
    assert not evaluator._passes_gate(report)


def test_gate_recomputes_score_and_cannot_hide_bad_judge_in_summary():
    report = completed_report()
    report["turns"]["details"][0]["judge"]["grounding"] = 1
    assert not evaluator._passes_gate(report)
    report["turns"]["details"][0]["judge"]["grounding"] = 99
    assert not evaluator._passes_gate(report)


def test_campaign_is_finite_before_generation(tmp_path):
    args = args_for(tmp_path, "turn")
    write_case(args.turn_dataset, evaluator.DEFAULT_TURN_DATASET)
    selected = evaluator._prepare_cases(args)
    args.max_model_calls = 1
    with pytest.raises(ValueError, match="upper bound"):
        evaluator._manifest(args, selected)


@pytest.mark.asyncio
async def test_frozen_model_judge_config_and_checkpoint_are_used(tmp_path, monkeypatch):
    from app.interviews.application.mock_interview_service import MockPlan, NextTurn

    args = args_for(tmp_path, "turn")
    write_case(args.turn_dataset, evaluator.DEFAULT_TURN_DATASET)
    inner = SimpleNamespace(
        _profile=SimpleNamespace(
            provider="deepseek",
            model="configured-primary",
            context_window=32000,
            max_output_tokens=1000,
        )
    )
    observed = []
    monkeypatch.setattr(evaluator, "get_llm_for_role", lambda *a, **k: inner)
    config = EvaluationLLMConfig(
        "never-print-this", "https://example.test/v1", "judge-only", None
    )
    monkeypatch.setattr(evaluator, "load_judge_llm_config", lambda: config)
    monkeypatch.setattr(
        evaluator,
        "generate_plan",
        lambda **k: (
            observed.append(k["llm"])
            or MockPlan([{"key": "self_intro"}], "请介绍自己", "self_intro")
        ),
    )

    async def generate(**k):
        observed.append(k["llm"])
        return NextTurn("请具体说明你的个人贡献？", "self_intro", False)

    monkeypatch.setattr(evaluator, "generate_next_turn", generate)
    fake = SimpleNamespace(
        complete=AsyncMock(return_value=json.dumps(valid_judge())), aclose=AsyncMock()
    )
    monkeypatch.setattr(
        evaluator, "MockJudgeClient", lambda cfg, j: observed.append(cfg) or fake
    )
    checkpoints = []
    result = await evaluator._run(
        args, checkpoint=lambda r: checkpoints.append(copy.deepcopy(r))
    )
    assert result["gate_passed"] is True
    assert result["manifest"]["judge"]["model"] == "judge-only"
    assert observed[0] == config
    assert observed[1] is observed[2]
    assert observed[1].inner is inner
    assert fake.aclose.await_count == 1
    assert "never-print-this" not in repr(result) + repr(config)
    assert checkpoints[0]["status"] == "running"
    assert result["trajectories"]["status"] == "not_run"


@pytest.mark.asyncio
async def test_judge_transport_has_one_attempt_and_unknown_is_retained(tmp_path):
    create = AsyncMock(side_effect=TimeoutError("private-provider-details"))
    sdk = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        close=AsyncMock(),
    )
    journal = CallJournal(2, tmp_path / "calls.jsonl")
    config = EvaluationLLMConfig("SECRET", "https://example.test/v1", "judge", None)
    judge = MockJudgeClient(config, journal, client=sdk)
    with pytest.raises(TimeoutError):
        await judge.complete("PRIVATE resume")
    assert create.await_count == 1
    assert journal.events[-1]["state"] == "unconfirmed"
    content = journal.path.read_text()
    assert (
        "PRIVATE" not in content
        and "SECRET" not in content
        and "private-provider" not in content
    )
    with pytest.raises(FileExistsError):
        CallJournal(2, journal.path)
    await judge.aclose()
    assert sdk.close.await_count == 1


@pytest.mark.asyncio
async def test_complete_invalid_judge_response_is_not_retried_or_unbilled():
    reply = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="length", message=SimpleNamespace(content="{}")
            )
        ],
        usage=None,
    )
    sdk = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=AsyncMock(return_value=reply))
        ),
        close=AsyncMock(),
    )
    journal = CallJournal(1)
    judge = MockJudgeClient(
        EvaluationLLMConfig("k", "https://example.test", "m", None), journal, client=sdk
    )
    with pytest.raises(ValueError, match="incomplete"):
        await judge.complete("x")
    assert journal.events[-1]["state"] == "response_received"
    assert sdk.chat.completions.create.await_count == 1


def test_journal_failure_before_dispatch_does_not_invoke_model(monkeypatch):
    journal = CallJournal(1)
    invoked = []
    generator = RecordedGenerator(
        SimpleNamespace(complete=lambda *a, **k: invoked.append(1)), journal
    )

    def fail(_event):
        raise OSError("full disk")

    monkeypatch.setattr(journal, "record", fail)
    with pytest.raises(OSError):
        generator.complete("x")
    assert not invoked


@pytest.mark.asyncio
async def test_shared_budget_counts_sync_async_and_rejects_before_sending():
    inner = SimpleNamespace(
        complete=lambda *a: "ok", acomplete=AsyncMock(return_value="ok")
    )
    journal = CallJournal(2)
    generator = RecordedGenerator(inner, journal)
    assert generator.complete("a") == "ok"
    assert await generator.acomplete("b") == "ok"
    with pytest.raises(CampaignLimitError):
        await generator.acomplete("c")
    assert inner.acomplete.await_count == 1


def test_atomic_report_does_not_remove_another_temporary_file(tmp_path):
    output = tmp_path / "report.json"
    output.write_text("original")
    temporary = tmp_path / "report.json.tmp"
    temporary.write_text("other")
    with pytest.raises(FileExistsError):
        write_report(output, {"x": 1})
    assert temporary.read_text() == "other"
    assert output.read_text() == "original"
    temporary.unlink()
    write_report(output, {"x": 1})
    assert json.loads(output.read_text()) == {"x": 1}


def test_gate_rejects_positive_summary_for_failed_or_untyped_checks():
    report = completed_report()
    report["turns"]["details"][0]["checks"]["valid_stage"] = False
    assert not evaluator._passes_gate(report)
    report["turns"]["details"][0]["checks"]["valid_stage"] = "false"
    assert not evaluator._passes_gate(report)


def test_every_quality_rate_uses_the_ten_point_cutoff():
    below = sample_result()
    below["passed"] = False
    below["judge"] = {
        **dict.fromkeys(JUDGE_DIMENSIONS, 7.9),
        "reason": "Below the documented 8/10 requirement.",
    }
    below["judge_mean"] = 7.9
    summary = evaluator._aggregate_turns([below])
    assert summary["pass_rate"] == 0
    assert summary["safety_pass_rate"] == 0
    assert summary["grounding_pass_rate"] == 0
    assert summary["language_pass_rate"] == 0
    at = sample_result()
    at["judge"] = {
        **dict.fromkeys(JUDGE_DIMENSIONS, 8),
        "reason": "Meets the requirement.",
    }
    at["judge_mean"] = 8
    summary = evaluator._aggregate_turns([at])
    assert summary["pass_rate"] == summary["safety_pass_rate"] == 1
