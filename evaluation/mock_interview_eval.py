"""Run model-backed quality regression for the production mock interviewer."""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.llm_client_factory import get_internal_llm  # noqa: E402
from app.prompts.interview import MOCK_INTERVIEW_JUDGE_PROMPT  # noqa: E402
from app.services.interview.mock_interview_service import (  # noqa: E402
    build_prefix,
    generate_next_turn,
    generate_plan,
)


DEFAULT_DATASET = Path(__file__).with_name("mock_interview_dataset.jsonl")


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


def _structure_checks(case: dict[str, Any], message: str, stage: str, finish: bool):
    forbidden = [str(item) for item in case.get("forbidden", [])]
    duplicates = [
        question
        for question in case.get("asked_questions", [])
        if SequenceMatcher(None, question, message).ratio() >= 0.82
    ]
    checks = {
        "non_empty": 5 <= len(message.strip()) <= 800,
        # A single focused topic may naturally use a clarification plus one
        # follow-up mark in Chinese. More than two usually indicates question
        # stacking; semantic focus is scored separately by the judge.
        "bounded_questions": message.count("?") + message.count("？") <= 2,
        "valid_stage": stage in case["allowed_stages"],
        "finish_signal": finish is bool(case["expect_finish"]),
        "no_forbidden_text": not any(item in message for item in forbidden),
        "no_duplicate_question": not duplicates,
    }
    return checks


async def _judge(
    case: dict[str, Any],
    message: str,
    generated_stage: str,
    ready_to_finish: bool,
) -> dict[str, Any]:
    payload = {
        key: case[key]
        for key in (
            "style",
            "resume",
            "jd",
            "current_stage",
            "recent_messages",
            "user_answer",
            "asked_questions",
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
    for key in ("relevance", "follow_up", "naturalness", "grounding", "safety"):
        result[key] = max(1, min(5, int(result[key])))
    return result


async def _evaluate(case: dict[str, Any], username: str) -> dict[str, Any]:
    plan = generate_plan(interviewer_style=case["style"])
    started = time.perf_counter()
    turn = await generate_next_turn(
        prefix=build_prefix(case["resume"], case["jd"], case["style"]),
        stages=plan.stages,
        current_stage_key=case["current_stage"],
        recent_messages=case["recent_messages"],
        user_answer=case["user_answer"],
        user_id=username,
        asked_questions=case["asked_questions"],
        questions_in_current_stage=case["questions_in_current_stage"],
    )
    judge = await _judge(
        case,
        turn.interviewer_message,
        turn.next_stage_key,
        turn.is_ready_to_finish,
    )
    checks = _structure_checks(
        case,
        turn.interviewer_message,
        turn.next_stage_key,
        turn.is_ready_to_finish,
    )
    judge_mean = statistics.mean(
        judge[key]
        for key in ("relevance", "follow_up", "naturalness", "grounding", "safety")
    )
    passed = (
        all(checks.values())
        and judge_mean >= 4
        and judge["grounding"] >= 4
        and judge["safety"] >= 4
    )
    return {
        "id": case["id"],
        "passed": passed,
        "message": turn.interviewer_message,
        "stage": turn.next_stage_key,
        "ready_to_finish": turn.is_ready_to_finish,
        "checks": checks,
        "judge": judge,
        "judge_mean": round(judge_mean, 3),
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
    }


async def _run(cases: list[dict[str, Any]], username: str) -> dict[str, Any]:
    details = []
    for index, case in enumerate(cases, 1):
        result = await _evaluate(case, username)
        details.append(result)
        print(
            f"[{index}/{len(cases)}] {case['id']}: "
            f"{'PASS' if result['passed'] else 'FAIL'} "
            f"(judge={result['judge_mean']:.2f})"
        )
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
        "latency_ms": {
            "mean": round(statistics.mean(item["latency_ms"] for item in details), 1),
            "max": round(max(item["latency_ms"] for item in details), 1),
        },
        "details": details,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--user", default="eval_user_a")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = asyncio.run(_run(_load_cases(args.dataset), args.user))
    output = args.output or (
        PROJECT_ROOT / "data" / "evaluation" / "mock_interview_report.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({k: v for k, v in result.items() if k != "details"}, indent=2))
    print(f"Report saved to: {output}")
    if (
        result["pass_rate"] < 0.85
        or result["mean_judge_score"] < 4
        or result["safety_pass_rate"] < 1
        or result["grounding_pass_rate"] < 1
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
