"""Mock-interview session-state serialization helpers.

The ``chat_sessions.mock_interview_state`` column holds the mock-interview
runtime state as a JSON blob (NULL for non-mock sessions). These helpers
serialize / deserialize it. ``general`` and ``debrief`` sessions do NOT use
this column — their identity lives in dedicated columns (``session_type`` /
``interview_id`` / ``summary``).
"""

import json
from typing import Any


def default_mock_state(interview_id: str = "") -> dict[str, Any]:
    """The placeholder state stored when a mock-interview session is created;
    ``/chat/mock-interview/start`` overwrites it with the full plan."""
    return {
        "mode": "mock_interview",
        "interview_id": interview_id,
        "current_phase": "",
        "current_question_idx": 0,
        "phase_history": [],
        "is_finished": False,
    }


def parse_mock_state(raw: str | None) -> dict[str, Any]:
    """Safely parse a ``mock_interview_state`` JSON blob, preserving any extra
    keys (e.g. schema-v2 ``interview_plan``) and filling in v1 defaults."""
    default = default_mock_state()
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


def dump_mock_state(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


__all__ = [
    "default_mock_state",
    "parse_mock_state",
    "dump_mock_state",
]
