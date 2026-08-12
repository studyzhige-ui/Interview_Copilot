import asyncio
from types import SimpleNamespace

from app.conversation.runtime_profile import (
    CAREER_RUNTIME,
    DEBRIEF_RUNTIME,
    MOCK_INTERVIEW_RUNTIME,
    runtime_profile_for_type,
)


def test_runtime_mode_policy_matches_product_boundaries():
    assert runtime_profile_for_type("general") is CAREER_RUNTIME
    assert CAREER_RUNTIME.resolve_mode("chat", "chat") == "agent"
    assert CAREER_RUNTIME.resolve_mode(None, None) == "agent"

    assert runtime_profile_for_type("debrief") is DEBRIEF_RUNTIME
    assert DEBRIEF_RUNTIME.resolve_mode("chat", None) == "chat"
    assert DEBRIEF_RUNTIME.resolve_mode("chat", "agent") == "agent"

    assert runtime_profile_for_type("mock_interview") is MOCK_INTERVIEW_RUNTIME
    assert MOCK_INTERVIEW_RUNTIME.resolve_mode("agent", "agent") == "chat"


def test_career_runtime_has_no_debrief_domain_context():
    context = asyncio.run(
        CAREER_RUNTIME.prepare_turn(
            {
                "type": "general",
                "subject_type": "interview_record",
                "subject_id": "should-not-load",
                "user_id": 1,
            }
        )
    )

    assert context.profile == "career"
    assert context.planner_question_catalog is None
    assert context.render_record_context((1,), (2,)) == ""


def test_debrief_runtime_loads_and_renders_selected_questions(monkeypatch):
    reference = SimpleNamespace(question_catalog=[(1, "自我介绍"), (2, "项目难点")])
    calls: list[tuple[object, tuple[int, ...]]] = []

    monkeypatch.setattr(
        "app.conversation.runtime_profile.load_interview_reference",
        lambda record_id, user_id: (
            reference if (record_id, user_id) == ("record-1", 7) else None
        ),
    )
    monkeypatch.setattr(
        "app.conversation.runtime_profile.render_interview_reference",
        lambda loaded, indexes: calls.append((loaded, tuple(indexes))) or "RECORD",
    )

    context = asyncio.run(
        DEBRIEF_RUNTIME.prepare_turn(
            {
                "type": "debrief",
                "subject_type": "interview_record",
                "subject_id": "record-1",
                "user_id": 7,
            }
        )
    )

    assert context.planner_question_catalog == reference.question_catalog
    assert context.render_record_context((2, 2, 99), (1, 2)) == "RECORD"
    assert calls == [(reference, (2, 1))]
