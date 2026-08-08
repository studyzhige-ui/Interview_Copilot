"""Run model-backed single-turn and full-trajectory mock-interview evaluation."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import sys
import time
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Awaitable, Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.llm_client_factory import get_internal_llm  # noqa: E402
from app.prompts.interview import MOCK_INTERVIEW_JUDGE_PROMPT  # noqa: E402
from app.services.interview.mock_interview_service import (  # noqa: E402
    NextTurn,
    build_prefix,
    detect_response_language,
    generate_next_turn,
    generate_plan,
)

DEFAULT_TURN_DATASET = Path(__file__).with_name("mock_interview_dataset.jsonl")
DEFAULT_TRAJECTORY_DATASET = Path(__file__).with_name(
    "mock_interview_trajectory_dataset.jsonl"
)
JUDGE_DIMENSIONS = (
    "relevance",
    "follow_up",
    "naturalness",
    "grounding",
    "safety",
    "language_fit",
)
TurnGenerator = Callable[..., Awaitable[NextTurn]]
TurnJudge = Callable[[dict[str, Any], str, str, bool], Awaitable[dict[str, Any]]]


def _load_cases(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def _parse_json(text: str) -> dict[str, Any]:
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].removesuffix("```").strip()
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Judge output must be a JSON object")
    return data


def _expected_language(answer: str) -> str:
    return detect_response_language(answer)


def _language_matches(expected: str, message: str) -> bool:
    if expected == "any":
        return True
    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", message))
    english_words = len(re.findall(r"[A-Za-z]{2,}", message))
    if expected == "zh":
        return cjk_count >= 4
    if expected == "en":
        return english_words >= 4
    return cjk_count >= 2 and english_words >= 2


def _structure_checks(
    case: dict[str, Any],
    message: str,
    stage: str,
    finish: bool,
) -> dict[str, bool]:
    forbidden = [str(item) for item in case.get("forbidden", [])]
    duplicates = [
        question
        for question in case.get("asked_questions", [])
        if SequenceMatcher(None, question, message).ratio() >= 0.82
    ]
    expected_finish = case.get("expect_finish")
    return {
        "non_empty": 5 <= len(message.strip()) <= 800,
        "bounded_questions": message.count("?") + message.count("？") <= 2,
        "valid_stage": stage in case["allowed_stages"],
        "finish_signal": (
            True if expected_finish is None else finish is bool(expected_finish)
        ),
        "no_forbidden_text": not any(item in message for item in forbidden),
        "no_duplicate_question": not duplicates,
        "language_fit": _language_matches(
            str(case.get("expected_language") or "any"), message
        ),
    }


async def _judge(
    case: dict[str, Any],
    message: str,
    generated_stage: str,
    ready_to_finish: bool,
) -> dict[str, Any]:
    payload = {
        key: case.get(key)
        for key in (
            "style",
            "resume",
            "jd",
            "current_stage",
            "recent_messages",
            "user_answer",
            "asked_questions",
            "questions_in_current_stage",
            "transition_rule",
            "expected_language",
        )
    }
    payload["generated_stage"] = generated_stage
    payload["ready_to_finish"] = ready_to_finish
    prompt = MOCK_INTERVIEW_JUDGE_PROMPT.format(
        case_json=json.dumps(payload, ensure_ascii=False),
        message=message,
    )
    response = await get_internal_llm("worker").acomplete(
        prompt,
        response_format={"type": "json_object"},
    )
    result = _parse_json(str(response.text))
    for key in JUDGE_DIMENSIONS:
        result[key] = max(1, min(5, int(result[key])))
    return result


def _judge_mean(judge: dict[str, Any]) -> float:
    return statistics.mean(judge[key] for key in JUDGE_DIMENSIONS)


async def _evaluate_turn(
    case: dict[str, Any],
    username: str,
    *,
    turn_generator: TurnGenerator = generate_next_turn,
    judge_turn: TurnJudge = _judge,
) -> dict[str, Any]:
    plan = generate_plan(interviewer_style=case["style"])
    started = time.perf_counter()
    turn = await turn_generator(
        prefix=build_prefix(case["resume"], case["jd"], case["style"]),
        stages=plan.stages,
        current_stage_key=case["current_stage"],
        recent_messages=case["recent_messages"],
        user_answer=case["user_answer"],
        user_id=username,
        asked_questions=case["asked_questions"],
        questions_in_current_stage=case["questions_in_current_stage"],
    )
    evaluated_case = {
        **case,
        "expected_language": case.get("expected_language")
        or _expected_language(case["user_answer"]),
    }
    stage_config = next(
        stage for stage in plan.stages if stage["key"] == case["current_stage"]
    )
    count = int(case["questions_in_current_stage"])
    evaluated_case["transition_rule"] = (
        "must_advance"
        if count >= int(stage_config["max_questions"])
        else "must_stay"
        if count < int(stage_config["min_questions"])
        else "may_advance"
    )
    judge = await judge_turn(
        evaluated_case,
        turn.interviewer_message,
        turn.next_stage_key,
        turn.is_ready_to_finish,
    )
    checks = _structure_checks(
        evaluated_case,
        turn.interviewer_message,
        turn.next_stage_key,
        turn.is_ready_to_finish,
    )
    checks["model_generation_succeeded"] = not turn.used_fallback
    mean_score = _judge_mean(judge)
    passed = (
        all(checks.values())
        and mean_score >= 4
        and judge["grounding"] >= 4
        and judge["safety"] >= 4
        and judge["language_fit"] >= 4
    )
    return {
        "id": case["id"],
        "passed": passed,
        "message": turn.interviewer_message,
        "stage": turn.next_stage_key,
        "ready_to_finish": turn.is_ready_to_finish,
        "checks": checks,
        "judge": judge,
        "judge_mean": round(mean_score, 3),
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
    }


def _initial_questions(case: dict[str, Any], plan) -> list[dict[str, str]]:
    configured = case.get("initial_questions")
    if configured:
        return [
            {"text": str(item["text"]), "stage_key": str(item["stage_key"])}
            for item in configured
        ]
    return [{"text": plan.opening_message, "stage_key": plan.first_stage_key}]


def _next_answer(
    case: dict[str, Any],
    stage: str,
    turn_index: int,
    stage_answer_counts: Counter[str],
) -> str | None:
    answers_by_stage = case.get("answers_by_stage")
    if isinstance(answers_by_stage, dict):
        answers = answers_by_stage.get(stage) or []
        index = stage_answer_counts[stage]
        if index >= len(answers):
            return None
        stage_answer_counts[stage] += 1
        return str(answers[index])
    steps = case.get("steps") or []
    if turn_index >= len(steps):
        return None
    return str(steps[turn_index]["answer"])


async def _evaluate_trajectory(
    case: dict[str, Any],
    username: str,
    *,
    turn_generator: TurnGenerator = generate_next_turn,
    judge_turn: TurnJudge = _judge,
) -> dict[str, Any]:
    plan = generate_plan(interviewer_style=case["style"])
    stage_keys = [stage["key"] for stage in plan.stages]
    current_stage = str(case.get("current_stage") or plan.first_stage_key)
    recent_messages = list(case.get("recent_messages") or [])
    questions = _initial_questions(case, plan)
    visited_stages = [current_stage]
    stage_answer_counts: Counter[str] = Counter()
    details: list[dict[str, Any]] = []
    recovery_turns = {int(item) for item in case.get("disconnect_after_turns", [])}
    recovered = 0
    max_turns = int(case.get("max_turns") or len(case.get("steps") or []))
    ready_to_finish = False

    for turn_index in range(max_turns):
        answer = _next_answer(case, current_stage, turn_index, stage_answer_counts)
        if answer is None:
            break
        prior_stage = current_stage
        prior_index = stage_keys.index(prior_stage)
        asked_text = [item["text"] for item in questions]
        questions_in_stage = sum(item["stage_key"] == prior_stage for item in questions)
        started = time.perf_counter()
        turn = await turn_generator(
            prefix=build_prefix(case["resume"], case["jd"], case["style"]),
            stages=plan.stages,
            current_stage_key=prior_stage,
            recent_messages=recent_messages[-8:],
            user_answer=answer,
            user_id=username,
            asked_questions=asked_text,
            questions_in_current_stage=questions_in_stage,
        )
        allowed_stages = [prior_stage]
        if prior_index + 1 < len(stage_keys):
            allowed_stages.append(stage_keys[prior_index + 1])
        step = (case.get("steps") or [{}])[turn_index] if case.get("steps") else {}
        evaluated_case = {
            **case,
            "current_stage": prior_stage,
            "recent_messages": recent_messages[-8:],
            "user_answer": answer,
            "asked_questions": asked_text,
            "allowed_stages": allowed_stages,
            "expect_finish": step.get("expect_finish"),
            "forbidden": [*case.get("forbidden", []), *step.get("forbidden", [])],
            "expected_language": step.get("expected_language")
            or _expected_language(answer),
            "questions_in_current_stage": questions_in_stage,
            "transition_rule": (
                "must_advance"
                if questions_in_stage >= int(plan.stages[prior_index]["max_questions"])
                else "must_stay"
                if questions_in_stage < int(plan.stages[prior_index]["min_questions"])
                else "may_advance"
            ),
        }
        judge = await judge_turn(
            evaluated_case,
            turn.interviewer_message,
            turn.next_stage_key,
            turn.is_ready_to_finish,
        )
        checks = _structure_checks(
            evaluated_case,
            turn.interviewer_message,
            turn.next_stage_key,
            turn.is_ready_to_finish,
        )
        checks["model_generation_succeeded"] = not turn.used_fallback
        checks["finish_only_on_final_stage"] = (
            not turn.is_ready_to_finish or turn.next_stage_key == stage_keys[-1]
        )
        mean_score = _judge_mean(judge)
        passed = (
            all(checks.values())
            and mean_score >= 4
            and judge["grounding"] >= 4
            and judge["safety"] >= 4
            and judge["language_fit"] >= 4
        )
        details.append(
            {
                "turn": turn_index + 1,
                "passed": passed,
                "answer": answer,
                "message": turn.interviewer_message,
                "from_stage": prior_stage,
                "stage": turn.next_stage_key,
                "ready_to_finish": turn.is_ready_to_finish,
                "checks": checks,
                "judge": judge,
                "judge_mean": round(mean_score, 3),
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            }
        )
        print(
            f"  {case['id']} turn {turn_index + 1}/{max_turns}: "
            f"{'PASS' if passed else 'FAIL'} {prior_stage}->{turn.next_stage_key}",
            flush=True,
        )

        recent_messages.extend(
            [
                {"role": "user", "content": answer},
                {"role": "assistant", "content": turn.interviewer_message},
            ]
        )
        questions.append(
            {"text": turn.interviewer_message, "stage_key": turn.next_stage_key}
        )
        current_stage = turn.next_stage_key
        if current_stage != visited_stages[-1]:
            visited_stages.append(current_stage)
        ready_to_finish = turn.is_ready_to_finish

        # Simulate a response committed by the server but lost to the browser.
        # Recovery resumes from the persisted logical state and must not invoke
        # the model twice for the same answer.
        if turn_index + 1 in recovery_turns:
            recovered += 1
        if ready_to_finish:
            break

    required_stages = case.get("required_stages") or []
    trajectory_checks = {
        "all_turns_pass": bool(details) and all(item["passed"] for item in details),
        "required_stages_visited": all(
            stage in visited_stages for stage in required_stages
        ),
        "completion": (
            ready_to_finish if case.get("expect_complete") else not ready_to_finish
        ),
        "disconnects_recovered": recovered == len(recovery_turns),
    }
    return {
        "id": case["id"],
        "passed": all(trajectory_checks.values()),
        "checks": trajectory_checks,
        "visited_stages": visited_stages,
        "recovered_disconnects": recovered,
        "turns": len(details),
        "details": details,
    }


def _aggregate_turns(details: list[dict[str, Any]]) -> dict[str, Any]:
    if not details:
        return {"samples": 0, "passed": 0, "pass_rate": 1.0, "details": []}
    return {
        "samples": len(details),
        "passed": sum(item["passed"] for item in details),
        "pass_rate": round(sum(item["passed"] for item in details) / len(details), 4),
        "mean_judge_score": round(
            statistics.mean(item["judge_mean"] for item in details), 4
        ),
        "safety_pass_rate": round(
            sum(item["judge"]["safety"] >= 4 for item in details) / len(details), 4
        ),
        "grounding_pass_rate": round(
            sum(item["judge"]["grounding"] >= 4 for item in details) / len(details),
            4,
        ),
        "language_pass_rate": round(
            sum(item["judge"]["language_fit"] >= 4 for item in details) / len(details),
            4,
        ),
        "latency_ms": {
            "mean": round(statistics.mean(item["latency_ms"] for item in details), 1),
            "max": round(max(item["latency_ms"] for item in details), 1),
        },
        "details": details,
    }


async def _run_turns(cases: list[dict[str, Any]], username: str) -> dict[str, Any]:
    details = []
    for index, case in enumerate(cases, 1):
        result = await _evaluate_turn(case, username)
        details.append(result)
        print(
            f"[turn {index}/{len(cases)}] {case['id']}: "
            f"{'PASS' if result['passed'] else 'FAIL'} "
            f"(judge={result['judge_mean']:.2f})"
        )
    return _aggregate_turns(details)


async def _run_trajectories(
    cases: list[dict[str, Any]], username: str
) -> dict[str, Any]:
    details = []
    for index, case in enumerate(cases, 1):
        result = await _evaluate_trajectory(case, username)
        details.append(result)
        print(
            f"[trajectory {index}/{len(cases)}] {case['id']}: "
            f"{'PASS' if result['passed'] else 'FAIL'} "
            f"({result['turns']} turns)"
        )
    all_turns = [turn for item in details for turn in item["details"]]
    turn_metrics = _aggregate_turns(all_turns)
    return {
        "samples": len(details),
        "passed": sum(item["passed"] for item in details),
        "pass_rate": round(sum(item["passed"] for item in details) / len(details), 4)
        if details
        else 1.0,
        "turn_metrics": {k: v for k, v in turn_metrics.items() if k != "details"},
        "details": details,
    }


async def _run(args) -> dict[str, Any]:
    def selected(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not args.case:
            return cases
        wanted = set(args.case)
        matches = [case for case in cases if case["id"] in wanted]
        missing = wanted - {case["id"] for case in matches}
        if missing:
            raise ValueError(f"unknown evaluation case(s): {sorted(missing)}")
        return matches

    turns = (
        await _run_turns(selected(_load_cases(args.turn_dataset)), args.user)
        if args.mode in {"all", "turn"}
        else _aggregate_turns([])
    )
    trajectories = (
        await _run_trajectories(
            selected(_load_cases(args.trajectory_dataset)), args.user
        )
        if args.mode in {"all", "trajectory"}
        else {"samples": 0, "passed": 0, "pass_rate": 1.0, "details": []}
    )
    return {"turns": turns, "trajectories": trajectories}


def _passes_gate(result: dict[str, Any]) -> bool:
    turns = result["turns"]
    trajectories = result["trajectories"]
    turn_gate = turns["samples"] == 0 or (
        turns["pass_rate"] >= 0.85
        and turns["mean_judge_score"] >= 4
        and turns["safety_pass_rate"] == 1
        and turns["grounding_pass_rate"] == 1
        and turns["language_pass_rate"] == 1
    )
    trajectory_gate = trajectories["samples"] == 0 or (
        trajectories["pass_rate"] >= 0.8
        and trajectories["turn_metrics"]["safety_pass_rate"] == 1
        and trajectories["turn_metrics"]["grounding_pass_rate"] == 1
        and trajectories["turn_metrics"]["language_pass_rate"] == 1
    )
    return turn_gate and trajectory_gate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("all", "turn", "trajectory"), default="all")
    parser.add_argument("--turn-dataset", type=Path, default=DEFAULT_TURN_DATASET)
    parser.add_argument(
        "--trajectory-dataset", type=Path, default=DEFAULT_TRAJECTORY_DATASET
    )
    parser.add_argument("--user", default="eval_user_a")
    parser.add_argument(
        "--case",
        action="append",
        help="Run one case id; repeat the option to select multiple cases.",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = asyncio.run(_run(args))
    output = args.output or (
        PROJECT_ROOT / "data" / "evaluation" / "mock_interview_report.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    summary = {
        "turns": {k: v for k, v in result["turns"].items() if k != "details"},
        "trajectories": {
            k: v for k, v in result["trajectories"].items() if k != "details"
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Report saved to: {output}")
    if not _passes_gate(result):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
