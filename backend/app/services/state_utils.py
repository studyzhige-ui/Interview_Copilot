import json
from typing import Any


def default_working_state_payload() -> dict[str, Any]:
    return {
        "goal": "",
        "current_phase": "",
        "covered_topics": [],
        "pending_topics": [],
        "candidate_claims_to_verify": [],
        "observed_gaps": [],
        "next_best_question": "",
        "constraints": [],
        "summary": "",
    }


def default_interview_state_payload() -> dict[str, Any]:
    return {
        "goal": "",
        "phase": "",
        "covered_topics": [],
        "pending_topics": [],
        "observed_gaps": [],
        "evidence": [],
        "candidate_claims": [],
        "next_question": "",
        "constraints": [],
    }


def parse_state_blob(raw: str | None, default_factory) -> dict[str, Any]:
    state = default_factory()
    if not raw:
        return state
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return state
    if not isinstance(parsed, dict):
        return state
    state.update(parsed)
    return state


def dump_state_blob(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def summarize_working_state(payload: dict[str, Any]) -> str:
    summary = str(payload.get("summary") or "").strip()
    if summary:
        return summary[:150]

    goal = str(payload.get("goal") or "").strip()
    phase = str(payload.get("current_phase") or "").strip()
    pending = payload.get("pending_topics") or []
    parts = [part for part in (goal, phase) if part]
    if pending:
        parts.append(f"pending: {', '.join(str(item) for item in pending[:2])}")
    return " | ".join(parts)[:150]
