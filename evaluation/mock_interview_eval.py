"""Run model-backed single-turn and full-trajectory mock-interview evaluation."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from functools import partial
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
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.llm_client_factory import get_llm_for_role  # noqa: E402
from app.core.scoring import QUALITY_PASS_SCORE, score_scale  # noqa: E402
from evaluation.llm_factory import load_judge_llm_config  # noqa: E402
from evaluation.mock_contracts import (  # noqa: E402
    JUDGE_DIMENSIONS,
    JudgeResult,
    TurnCase,
    TrajectoryCase,
    strict_json,
)
from evaluation.mock_run import (  # noqa: E402
    CallJournal,
    MockJudgeClient,
    RecordedGenerator,
    write_report,
)
from app.prompts.interview import MOCK_INTERVIEW_JUDGE_PROMPT  # noqa: E402
from app.interviews.application.mock_interview_service import MockPlan  # noqa: E402 — CLI package bootstrap above
from app.interviews.application.mock_interview_service import NextTurn  # noqa: E402 — CLI package bootstrap above
from app.interviews.application.mock_interview_service import build_prefix  # noqa: E402 — CLI package bootstrap above
from app.interviews.application.mock_interview_service import detect_response_language  # noqa: E402 — CLI package bootstrap above
from app.interviews.application.mock_interview_service import generate_next_turn  # noqa: E402 — CLI package bootstrap above
from app.interviews.application.mock_interview_service import generate_plan  # noqa: E402 — CLI package bootstrap above

DEFAULT_TURN_DATASET = Path(__file__).with_name("mock_interview_dataset.jsonl")
DEFAULT_TRAJECTORY_DATASET = Path(__file__).with_name(
    "mock_interview_trajectory_dataset.jsonl"
)
TurnGenerator = Callable[..., Awaitable[NextTurn]]
PlanGenerator = Callable[..., MockPlan]
TurnJudge = Callable[[dict[str, Any], str, str, bool], Awaitable[dict[str, Any]]]


def _load_cases(path: Path, kind: str | None = None) -> list[dict[str, Any]]:
    if path.stat().st_size > 8_000_000:
        raise ValueError("evaluation dataset exceeds capacity")
    cases = []
    seen = set()
    with path.open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, 1):
            if not line.strip():
                continue
            try:
                raw = strict_json(line)
                contract = (
                    TurnCase
                    if kind == "turn"
                    or (kind is None and isinstance(raw, dict) and "user_answer" in raw)
                    else TrajectoryCase
                )
                case = contract.model_validate(raw).model_dump(exclude_unset=True)
            except (ValueError, RecursionError):
                # A Pydantic error can contain private resume or answer text.
                raise ValueError(
                    f"invalid evaluation case at line {line_number}"
                ) from None
            if case["id"] in seen:
                raise ValueError(f"duplicate case id at line {line_number}")
            seen.add(case["id"])
            cases.append(case)
            if len(cases) > 1000:
                raise ValueError("too many evaluation cases")
    return cases


def _parse_json(text: str) -> dict[str, Any]:
    if not isinstance(text, str) or len(text.encode("utf-8")) > 64_000:
        raise ValueError("judge JSON exceeds capacity")
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].removesuffix("```").strip()
    data = strict_json(raw, max_bytes=64_000)
    return JudgeResult.model_validate(data).model_dump()


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
    already_ended_phrases = (
        "本次模拟面试到这里结束",
        "本次面试到这里结束",
        "面试已经结束",
        "interview is now over",
        "interview has ended",
    )
    return {
        "non_empty": 5 <= len(message.strip()) <= 800,
        "bounded_questions": message.count("?") + message.count("？") <= 2,
        "valid_stage": stage in case["allowed_stages"],
        "finish_signal": (
            True if expected_finish is None else finish is bool(expected_finish)
        ),
        "finish_is_advisory": not finish
        or not any(phrase in message.lower() for phrase in already_ended_phrases),
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
    *,
    client: MockJudgeClient | None = None,
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
            "length_warning_active",
            "expected_language",
        )
    }
    recent_messages = case.get("recent_messages") or []
    payload["previous_interviewer_question"] = next(
        (
            str(item.get("content") or "")
            for item in reversed(recent_messages)
            if str(item.get("role") or "").lower().startswith(("assistant", "agent"))
        ),
        "",
    )
    payload["generated_stage"] = generated_stage
    payload["ready_to_finish"] = ready_to_finish
    prompt = MOCK_INTERVIEW_JUDGE_PROMPT.format(
        case_json=json.dumps(payload, ensure_ascii=False),
        message=message,
    )
    # Same independently configurable judge as the RAG suite, not internal worker.
    owned = client is None
    if owned:
        client = MockJudgeClient(load_judge_llm_config(), CallJournal(1))
    try:
        return _parse_json(await client.complete(prompt))
    finally:
        if owned:
            await client.aclose()


def _judge_mean(judge: dict[str, Any]) -> float:
    validated = JudgeResult.model_validate(judge)
    return statistics.mean(getattr(validated, key) for key in JUDGE_DIMENSIONS)


async def _evaluate_turn(
    case: dict[str, Any],
    username: str,
    *,
    plan_generator: PlanGenerator = generate_plan,
    turn_generator: TurnGenerator = generate_next_turn,
    judge_turn: TurnJudge = _judge,
) -> dict[str, Any]:
    plan = plan_generator(
        resume_context=case["resume"],
        jd_context=case["jd"],
        interviewer_style=case["style"],
        user_id=username,
    )
    started = time.perf_counter()
    turn = await turn_generator(
        prefix=build_prefix(case["resume"], case["jd"], case["style"]),
        stages=plan.stages,
        current_stage_key=case["current_stage"],
        conversation_messages=case["recent_messages"],
        user_answer=case["user_answer"],
        user_id=username,
        length_warning_active=bool(case.get("length_warning_active", False)),
    )
    evaluated_case = {
        **case,
        "expected_language": case.get("expected_language")
        or _expected_language(case["user_answer"]),
    }
    generation_ms = (time.perf_counter() - started) * 1000
    judge_started = time.perf_counter()
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
    mean_score = _judge_mean(judge)
    passed = (
        all(checks.values())
        and mean_score >= QUALITY_PASS_SCORE
        and judge["grounding"] >= QUALITY_PASS_SCORE
        and judge["safety"] >= QUALITY_PASS_SCORE
        and judge["language_fit"] >= QUALITY_PASS_SCORE
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
        "latency_ms": round(generation_ms, 1),
        "judge_latency_ms": round((time.perf_counter() - judge_started) * 1000, 1),
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
    plan_generator: PlanGenerator = generate_plan,
    turn_generator: TurnGenerator = generate_next_turn,
    judge_turn: TurnJudge = _judge,
) -> dict[str, Any]:
    plan = plan_generator(
        resume_context=case["resume"],
        jd_context=case["jd"],
        interviewer_style=case["style"],
        user_id=username,
    )
    stage_keys = [stage["key"] for stage in plan.stages]
    current_stage = str(case.get("current_stage") or plan.first_stage_key)
    recent_messages = list(case.get("recent_messages") or [])
    questions = _initial_questions(case, plan)
    if not recent_messages:
        recent_messages = [{"role": "assistant", "content": questions[-1]["text"]}]
    visited_stages = [current_stage]
    stage_answer_counts: Counter[str] = Counter()
    details: list[dict[str, Any]] = []
    recovery_turns = set(case.get("disconnect_after_turns", []))
    reached_markers = 0
    max_turns = int(case.get("max_turns") or len(case.get("steps") or []))
    ready_to_finish = False

    for turn_index in range(max_turns):
        answer = _next_answer(case, current_stage, turn_index, stage_answer_counts)
        if answer is None:
            break
        prior_stage = current_stage
        prior_index = stage_keys.index(prior_stage)
        asked_text = [item["text"] for item in questions]
        started = time.perf_counter()
        turn = await turn_generator(
            prefix=build_prefix(case["resume"], case["jd"], case["style"]),
            stages=plan.stages,
            current_stage_key=prior_stage,
            conversation_messages=recent_messages,
            user_answer=answer,
            user_id=username,
            length_warning_active=bool(
                case.get("length_warning_active", False)
                or turn_index + 1 >= int(case.get("warning_turns") or 20)
            ),
        )
        allowed_stages = [prior_stage]
        if prior_index + 1 < len(stage_keys):
            allowed_stages.append(stage_keys[prior_index + 1])
        step = (case.get("steps") or [{}])[turn_index] if case.get("steps") else {}
        evaluated_case = {
            **case,
            "current_stage": prior_stage,
            "recent_messages": recent_messages,
            "user_answer": answer,
            "asked_questions": asked_text,
            "allowed_stages": allowed_stages,
            "expect_finish": step.get("expect_finish"),
            "forbidden": [*case.get("forbidden", []), *step.get("forbidden", [])],
            "expected_language": step.get("expected_language")
            or _expected_language(answer),
            "length_warning_active": bool(
                case.get("length_warning_active", False)
                or turn_index + 1 >= int(case.get("warning_turns") or 20)
            ),
        }
        generation_ms = (time.perf_counter() - started) * 1000
        judge_started = time.perf_counter()
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
        checks["finish_only_on_final_stage"] = (
            not turn.is_ready_to_finish or turn.next_stage_key == stage_keys[-1]
        )
        mean_score = _judge_mean(judge)
        passed = (
            all(checks.values())
            and mean_score >= QUALITY_PASS_SCORE
            and judge["grounding"] >= QUALITY_PASS_SCORE
            and judge["safety"] >= QUALITY_PASS_SCORE
            and judge["language_fit"] >= QUALITY_PASS_SCORE
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
                "latency_ms": round(generation_ms, 1),
                "judge_latency_ms": round(
                    (time.perf_counter() - judge_started) * 1000, 1
                ),
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

        # Dataset markers are not transport faults. Actual recovery belongs to
        # the separate PostgreSQL/Celery/browser tests, not this model loop.
        if turn_index + 1 in recovery_turns:
            reached_markers += 1
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
    }
    return {
        "id": case["id"],
        "passed": all(trajectory_checks.values()),
        "checks": trajectory_checks,
        "visited_stages": visited_stages,
        "recovery_validation": {
            "status": "not_exercised",
            "dataset_markers_reached": reached_markers,
            "reason": "model trajectory only; no transport or process was interrupted",
        },
        "turns": len(details),
        "details": details,
    }


def _checked_pass(item: dict[str, Any], *, trajectory: bool = False) -> bool:
    checks = item["checks"]
    if (
        not isinstance(checks, dict)
        or not checks
        or any(type(v) is not bool for v in checks.values())
    ):
        raise ValueError("invalid evaluation checks")
    if type(item.get("passed")) is not bool:
        raise ValueError("invalid evaluation pass indicator")
    actual = all(checks.values())
    if trajectory:
        children = item["details"]
        actual = (
            actual and bool(children) and all(_checked_pass(row) for row in children)
        )
    else:
        judge = item["judge"]
        actual = (
            actual
            and _judge_mean(judge) >= QUALITY_PASS_SCORE
            and all(
                judge[key] >= QUALITY_PASS_SCORE
                for key in ("grounding", "safety", "language_fit")
            )
        )
    if item["passed"] != actual:
        raise ValueError("evaluation summary disagrees with evidence")
    return actual


def _aggregate_turns(details: list[dict[str, Any]]) -> dict[str, Any]:
    if not details:
        return {
            "status": "empty",
            "samples": 0,
            "passed": 0,
            "pass_rate": None,
            "details": [],
        }
    means = [_judge_mean(item["judge"]) for item in details]
    passes = [_checked_pass(item) for item in details]
    return {
        "status": "completed",
        "samples": len(details),
        "passed": sum(passes),
        "pass_rate": sum(passes) / len(details),
        "mean_judge_score": statistics.mean(means),
        "safety_pass_rate": sum(
            item["judge"]["safety"] >= QUALITY_PASS_SCORE for item in details
        )
        / len(details),
        "grounding_pass_rate": sum(
            item["judge"]["grounding"] >= QUALITY_PASS_SCORE for item in details
        )
        / len(details),
        "language_pass_rate": sum(
            item["judge"]["language_fit"] >= QUALITY_PASS_SCORE for item in details
        )
        / len(details),
        "latency_ms": {
            "mean": round(statistics.mean(item["latency_ms"] for item in details), 1),
            "max": round(max(item["latency_ms"] for item in details), 1),
        },
        "details": details,
    }


def _aggregate_trajectories(details: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = _aggregate_turns([turn for item in details for turn in item["details"]])
    passes = [_checked_pass(item, trajectory=True) for item in details]
    return {
        "status": "completed" if details else "empty",
        "samples": len(details),
        "passed": sum(passes),
        "pass_rate": sum(passes) / len(details) if details else None,
        "turn_metrics": {k: v for k, v in metrics.items() if k != "details"},
        "details": details,
    }


def _prepare_cases(args) -> dict[str, list[dict[str, Any]]]:
    selected = {}
    if args.mode in {"all", "turn"}:
        selected["turns"] = _load_cases(args.turn_dataset, "turn")
    if args.mode in {"all", "trajectory"}:
        selected["trajectories"] = _load_cases(args.trajectory_dataset, "trajectory")
    wanted = set(args.case or [])
    available = {case["id"] for cases in selected.values() for case in cases}
    if wanted - available:
        raise ValueError(f"unknown evaluation case(s): {sorted(wanted - available)}")
    for section, cases in selected.items():
        matches = [c for c in cases if not wanted or c["id"] in wanted]
        if not matches:
            raise ValueError(
                f"selected {section} has no cases; select an appropriate --mode"
            )
        selected[section] = matches
    if not selected:
        raise ValueError("no evaluation mode selected")
    return selected


def _manifest(args, selected) -> dict[str, Any]:
    sources = [
        Path(__file__),
        Path(__file__).with_name("mock_contracts.py"),
        Path(__file__).with_name("mock_run.py"),
        Path(__file__).with_name("llm_factory.py"),
        BACKEND_ROOT / "app/prompts/interview.py",
        BACKEND_ROOT / "app/core/scoring.py",
        BACKEND_ROOT / "app/interviews/application/mock_interview_service.py",
    ]
    maximum = sum(
        4 * len(cases)
        if key == "turns"
        else sum(1 + 3 * case["max_turns"] for case in cases)
        for key, cases in selected.items()
    )
    cap = getattr(args, "max_model_calls", 256)
    if type(cap) is not int or not 1 <= cap <= 100_000 or maximum > cap:
        raise ValueError(
            f"campaign upper bound {maximum} exceeds --max-model-calls {cap}"
        )
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "score_scale": score_scale(),
        "judge_rubric_version": "mock-judge-10-v1",
        "sample_ids": {
            key: [case["id"] for case in cases] for key, cases in selected.items()
        },
        "sample_sha256": {
            key: hashlib.sha256(
                json.dumps(
                    cases, ensure_ascii=False, sort_keys=True, allow_nan=False
                ).encode()
            ).hexdigest()
            for key, cases in selected.items()
        },
        "source_sha256": {
            str(path.relative_to(PROJECT_ROOT)): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in sources
        },
        "model_call_upper_bound": maximum,
        "max_model_calls": cap,
        "automatic_transport_retries": 0,
        "quality_scope": "model-backed synthetic trajectories, not recovery or learning-effect validation",
        "judge_independence": "separate configuration/prompt; same-provider bias remains possible",
    }


async def _run(args, *, selected=None, journal=None, checkpoint=None) -> dict[str, Any]:
    selected = _prepare_cases(args) if selected is None else selected
    manifest = _manifest(args, selected)
    report = {
        "schema_version": 3,
        "score_scale": score_scale(),
        "status": "running",
        "requested_sections": list(selected),
        "manifest": manifest,
        "turns": {**_aggregate_turns([]), "status": "not_run"},
        "trajectories": {**_aggregate_trajectories([]), "status": "not_run"},
    }
    journal = journal or CallJournal(manifest["max_model_calls"])
    client = None
    try:
        # Resolve once, before any generation. Planning and all answers use the
        # same metered model instance, even if the user's selection later changes.
        generator = RecordedGenerator(
            get_llm_for_role("primary", user_id=args.user), journal
        )
        profile = generator._profile
        manifest["generator"] = {
            "provider": profile.provider,
            "model": profile.model,
            "context_window": profile.context_window,
            "max_output_tokens": profile.max_output_tokens,
        }
        judge_config = load_judge_llm_config()
        manifest["judge"] = {
            "model": judge_config.model,
            "endpoint_sha256": hashlib.sha256(
                judge_config.api_base.encode()
            ).hexdigest(),
            "temperature": 0,
            "max_tokens": 4096,
            "thinking_mode": judge_config.thinking_mode,
        }
        client = MockJudgeClient(judge_config, journal)
        dependencies = {
            "plan_generator": partial(generate_plan, llm=generator),
            "turn_generator": partial(generate_next_turn, llm=generator),
            "judge_turn": partial(_judge, client=client),
        }
        if checkpoint:
            checkpoint(report)
        for section, cases in selected.items():
            details = []
            evaluate = _evaluate_turn if section == "turns" else _evaluate_trajectory
            aggregate = (
                _aggregate_turns if section == "turns" else _aggregate_trajectories
            )
            for index, case in enumerate(cases, 1):
                result = await evaluate(case, args.user, **dependencies)
                details.append(result)
                report[section] = aggregate(details)
                report[section]["status"] = (
                    "running" if index < len(cases) else "completed"
                )
                report["model_calls_started"] = journal.count
                if checkpoint:
                    checkpoint(report)
                print(
                    f"[{section} {index}/{len(cases)}] {case['id']}: "
                    f"{'PASS' if result['passed'] else 'FAIL'}",
                    flush=True,
                )
        report["status"] = "completed"
        report["gate_passed"] = _passes_gate(report)
        return report
    except BaseException as exc:
        report["status"] = "interrupted"
        report["error_type"] = type(exc).__name__
        report["gate_passed"] = False
        report["model_calls_started"] = journal.count
        if checkpoint:
            checkpoint(report)
        raise
    finally:
        if client is not None:
            try:
                await client.aclose()
            except BaseException as exc:
                report["status"] = "interrupted"
                report["error_type"] = type(exc).__name__
                report["gate_passed"] = False
                if checkpoint:
                    checkpoint(report)
                raise


def _passes_gate(result: dict[str, Any]) -> bool:
    if (
        result.get("schema_version") != 3
        or result.get("status") != "completed"
        or result.get("score_scale") != score_scale()
    ):
        return False
    selected = result.get("requested_sections")
    if (
        not isinstance(selected, list)
        or not selected
        or not all(isinstance(s, str) for s in selected)
        or len(selected) != len(set(selected))
    ):
        return False
    try:
        for section in selected:
            if section not in {"turns", "trajectories"}:
                return False
            data = result[section]
            if data.get("status") != "completed" or not data.get("details"):
                return False
            if section == "turns":
                metrics = _aggregate_turns(data["details"])
                if (
                    metrics["pass_rate"] < 0.85
                    or metrics["mean_judge_score"] < QUALITY_PASS_SCORE
                ):
                    return False
            else:
                aggregate = _aggregate_trajectories(data["details"])
                metrics = aggregate["turn_metrics"]
                if aggregate["pass_rate"] < 0.8 or metrics["samples"] == 0:
                    return False
            if any(
                metrics[key] != 1
                for key in (
                    "safety_pass_rate",
                    "grounding_pass_rate",
                    "language_pass_rate",
                )
            ):
                return False
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("all", "turn", "trajectory"), default="all")
    parser.add_argument("--turn-dataset", type=Path, default=DEFAULT_TURN_DATASET)
    parser.add_argument(
        "--trajectory-dataset", type=Path, default=DEFAULT_TRAJECTORY_DATASET
    )
    parser.add_argument("--user", default="eval_user_a")
    parser.add_argument(
        "--case", action="append", help="Select case ids across the selected mode(s)."
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="New private report file; existing runs are never overwritten.",
    )
    parser.add_argument("--max-model-calls", type=int, default=256)
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="Validate data and print finite campaign manifest; no model or DB calls.",
    )
    args = parser.parse_args()
    # Preflight EVERY selected dataset before resolving credentials or sending a call.
    selected = _prepare_cases(args)
    manifest = _manifest(args, selected)
    if args.plan_only:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return
    output = (
        args.output
        or PROJECT_ROOT / "data/evaluation/mock" / f"{uuid.uuid4().hex}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        output.chmod(0o600)
        json.dump(
            {
                "schema_version": 3,
                "score_scale": score_scale(),
                "status": "preparing",
                "manifest": manifest,
            },
            handle,
        )
        handle.flush()
        os.fsync(handle.fileno())
    journal = CallJournal(args.max_model_calls, output.with_suffix(".calls.jsonl"))
    from app.usage.runtime import for_username

    try:
        with for_username(args.user):
            result = asyncio.run(
                _run(
                    args,
                    selected=selected,
                    journal=journal,
                    checkpoint=lambda report: write_report(output, report),
                )
            )
        write_report(output, result)
    except (Exception, KeyboardInterrupt) as exc:
        # Never print provider errors or retry a potentially paid call.
        print(
            f"Evaluation interrupted ({type(exc).__name__}); inspect {output} and its call journal.",
            file=sys.stderr,
        )
        raise SystemExit(2) from None
    print(f"Report saved to: {output}; gate_passed={result['gate_passed']}")
    if not result["gate_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
