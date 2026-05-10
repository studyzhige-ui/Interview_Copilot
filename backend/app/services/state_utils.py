import json
from typing import Any


def default_general_state() -> dict[str, Any]:
    return {"mode": "general", "summary": ""}


def default_debrief_state(interview_id: str = "") -> dict[str, Any]:
    return {
        "mode": "debrief",
        "interview_id": interview_id,
        "summary": "",
    }


def default_mock_state(interview_id: str = "") -> dict[str, Any]:
    return {
        "mode": "mock_interview",
        "interview_id": interview_id,
        "current_phase": "",
        "current_question_idx": 0,
        "phase_history": [],
        "is_finished": False,
    }


def default_session_state_for_type(
    session_type: str,
    interview_id: str = "",
) -> dict[str, Any]:
    """Return the default session_state dict for a given session type."""
    if session_type == "debrief":
        return default_debrief_state(interview_id)
    if session_type == "mock_interview":
        return default_mock_state(interview_id)
    return default_general_state()


def parse_session_state(raw: str | None, session_type: str = "general") -> dict[str, Any]:
    """Safely parse a session_state JSON blob, falling back to defaults."""
    default = default_session_state_for_type(session_type)
    if not raw:
        return default
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return default
    if not isinstance(parsed, dict):
        return default
    default.update(parsed)
    return default


def dump_session_state(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def summarize_session_state(payload: dict[str, Any]) -> str:
    """One-line summary for session list UI."""
    mode = payload.get("mode", "general")
    summary = str(payload.get("summary") or "").strip()
    if summary:
        return summary[:150]
    if mode == "mock_interview":
        phase = str(payload.get("current_phase") or "").strip()
        return f"模拟面试 | {phase}" if phase else "模拟面试"
    if mode == "debrief":
        return "面试复盘"
    return "通用对话"
