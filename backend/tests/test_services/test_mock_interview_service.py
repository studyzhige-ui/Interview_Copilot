"""Tests for app.services.interview.mock_interview_service (Runtime Director v6).

The old plan/state-machine API was removed in the v6 refactor. The new
surface is built around:
  - build_prefix / prefix_hash  (deterministic cacheable prefix)
  - generate_brief              (LLM #1, one-shot at session start)
  - run_director                (LLM #2, every turn, with validator + retry)
  - summarize_history           (LLM #3, rolling summary)
  - apply_state_update          (deterministic state mutator)
  - normalize_topic             (snake_case canonicalizer)
  - validate_director           (server-side guard)
"""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.interview import mock_interview_service as mod
from app.services.interview.mock_interview_service import (
    AnswerQuality,
    DEFAULT_TURN_BUDGETS,
    DirectorOutput,
    DirectorRetryExhausted,
    MAX_FOLLOW_UP_DEPTH,
    StateUpdate,
    apply_state_update,
    build_prefix,
    generate_brief,
    normalize_topic,
    prefix_hash,
    run_director,
    validate_director,
)


# ── opener invariants (BRIEF_PROMPT contract) ───────────────────────────


def test_fallback_brief_opener_satisfies_prompt_caps():
    """The prompt promises the LLM that ``opening_spoken`` ≤ 8 chars
    and ``opening_question`` ≤ 20 chars. The server-side fallback
    (used when the LLM returns garbage) MUST respect the same caps
    so the user-visible first message is identical in spirit
    whether the LLM succeeded or we fell back.

    Also pins the no-mixing rule: the opener must NOT contain
    interview-duration / JD-keyword / project-name leakage. The
    fallback strings are static so this test guards against a future
    contributor "improving" them and breaking the contract.
    """
    brief = mod._fallback_brief()

    # Length caps match the prompt.
    assert len(brief.opening_spoken) <= 8, (
        f"opening_spoken={brief.opening_spoken!r} exceeds 8-char cap"
    )
    assert len(brief.opening_question) <= 20, (
        f"opening_question={brief.opening_question!r} exceeds 20-char cap"
    )

    # Forbidden patterns (the screenshot's specific failure modes).
    forbidden = [
        "面试", "分钟", "JD", "岗位", "项目", "技术栈",
        "请详细", "请深入", "欢迎参加",
    ]
    combined = brief.opening_spoken + brief.opening_question
    for pat in forbidden:
        assert pat not in combined, (
            f"fallback opener leaks forbidden pattern {pat!r}; "
            f"got {combined!r}"
        )


# ── build_prefix / prefix_hash ───────────────────────────────────────────


def test_build_prefix_is_deterministic():
    """Same inputs → byte-identical prefix (DeepSeek prompt-cache stability)."""
    a = build_prefix("resume A", "jd A", "professional")
    b = build_prefix("resume A", "jd A", "professional")
    assert a == b
    # And every field is reflected in the output.
    assert "resume A" in a
    assert "jd A" in a


def test_build_prefix_falls_back_when_inputs_empty():
    prefix = build_prefix("", "", "professional")
    assert "未提供简历" in prefix
    assert "未提供 JD" in prefix


def test_prefix_hash_is_short_and_stable():
    h = prefix_hash("anything")
    assert isinstance(h, str)
    assert len(h) == 16
    assert prefix_hash("anything") == h


# ── normalize_topic ──────────────────────────────────────────────────────


def test_normalize_topic_canonicalizes():
    assert normalize_topic("Redis Cache") == "redis_cache"
    assert normalize_topic("  GO-Routine  ") == "go_routine"
    assert normalize_topic(None) == ""
    # Length cap at 40
    assert len(normalize_topic("x" * 100)) == 40


# ── apply_state_update ───────────────────────────────────────────────────


def test_apply_state_update_per_turn_cap_and_dedup():
    """Per-turn cap = 1 (only the first proposed entry is considered) and
    duplicates against existing entries are dropped."""
    # Case A: first proposed entry is brand new → added.
    # Pick a topic with no character overlap with the existing one — the dedup
    # is a cheap char-set similarity check (>0.7 == dup), so e.g. "kafka" vs
    # "ml_pipeline" is far enough apart.
    state = {"covered_topics": ["ml_pipeline"], "weak_topics": [], "strong_topics": []}
    apply_state_update(
        state,
        StateUpdate(covered_topics_add=["kafka", "tcp"], weak_topics_add=["redis_cache"]),
    )
    assert "ml_pipeline" in state["covered_topics"]
    assert "kafka" in state["covered_topics"]
    # Past the per-turn cap of 1 — never added.
    assert "tcp" not in state["covered_topics"]
    assert state["weak_topics"] == ["redis_cache"]

    # Case B: first proposed entry collides with an existing one → dropped,
    # and the cap means the second one never gets a chance either.
    state2 = {"covered_topics": ["kafka"], "weak_topics": [], "strong_topics": []}
    apply_state_update(
        state2,
        StateUpdate(covered_topics_add=["kafka", "tcp"]),
    )
    assert state2["covered_topics"] == ["kafka"]


def test_apply_state_update_weak_strong_exclusive():
    """Promoting a topic to 'strong' must remove it from 'weak' (and vice versa)."""
    state = {
        "covered_topics": [],
        "weak_topics": ["go_routine"],
        "strong_topics": [],
    }
    apply_state_update(state, StateUpdate(strong_topics_add=["go_routine"]))

    assert state["weak_topics"] == []
    assert state["strong_topics"] == ["go_routine"]


# ── validate_director ────────────────────────────────────────────────────


def _build_director(
    *,
    action="new_question",
    phase="technical",
    spoken="嗯，了解。",
    next_q="什么是缓存击穿？",
    topic="cache",
    should_finish=False,
):
    return DirectorOutput(
        action=action,
        phase=phase,
        spoken_response=spoken,
        next_question=next_q,
        topic=topic,
        answer_quality=AnswerQuality(level="partial", reason=""),
        state_update=StateUpdate(),
        should_finish=should_finish,
    )


def test_validate_director_ok():
    state = {"follow_up_depth": 0, "max_turns": 14, "turn_count": 5}
    assert validate_director(_build_director(), state) is None


def test_validate_director_follow_up_depth_cap():
    """follow_up beyond MAX_FOLLOW_UP_DEPTH must be rejected."""
    state = {"follow_up_depth": MAX_FOLLOW_UP_DEPTH, "max_turns": 14, "turn_count": 5}
    result = _build_director(action="follow_up", spoken="嗯", next_q="再细说一点？")
    violation = validate_director(result, state)
    assert violation is not None
    assert "follow_up" in violation.lower() or "追问" in violation


def test_validate_director_transition_must_have_phrase():
    """transition without a recognized transition phrase fails V6."""
    state = {"follow_up_depth": 0, "max_turns": 14, "turn_count": 5}
    bad = _build_director(action="transition", spoken="说说项目经历。", next_q="你做过什么项目？")
    violation = validate_director(bad, state)
    assert violation is not None

    good = _build_director(action="transition", spoken="接下来咱们换个角度。", next_q="你做过什么项目？")
    assert validate_director(good, state) is None


def test_validate_director_spoken_must_not_have_question_outside_clarify():
    state = {"follow_up_depth": 0, "max_turns": 14, "turn_count": 5}
    bad = _build_director(action="new_question", spoken="嗯，你确定吗？", next_q="什么是缓存？")
    violation = validate_director(bad, state)
    assert violation is not None
    assert "问号" in violation or "question" in violation.lower()


def test_validate_director_reverse_qa_first_entry_requires_invitation():
    state = {
        "follow_up_depth": 0,
        "max_turns": 14,
        "turn_count": 5,
        "reverse_qa_prompted": False,
    }
    bad = _build_director(
        action="new_question",
        phase="reverse_qa",
        spoken="进入下一阶段。",
        next_q="谈谈你的项目。",
    )
    violation = validate_director(bad, state)
    assert violation is not None


# ── generate_brief ───────────────────────────────────────────────────────


def test_generate_brief_parses_llm_output():
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "interview_plan": {
            "interview_goal": "考察 Redis 与系统设计",
            "candidate_focus": ["简历项目"],
            "jd_focus": ["Redis"],
            "phases": [
                {"phase": "self_intro", "budget": 1, "goal": "", "suggested_topics": [], "difficulty": "warm_up"},
                {"phase": "technical", "budget": 3, "goal": "", "suggested_topics": ["redis"], "difficulty": "core"},
            ],
        },
        "opening_spoken": "你好，开始吧。",
        "opening_question": "做个自我介绍。",
        "min_turns": 5,
        "target_turns": 8,
        "max_turns": 12,
    })

    with patch.object(mod, "_mock_llm") as mock_llm:
        mock_llm.acomplete = AsyncMock(return_value=mock_response)
        brief = asyncio.run(generate_brief(resume_context="r", jd_context="j"))

    assert brief.opening_spoken == "你好，开始吧。"
    assert brief.opening_question == "做个自我介绍。"
    assert brief.min_turns == 5
    assert brief.target_turns == 8
    assert brief.max_turns == 12
    # _normalize_plan fills in missing phases up to the canonical 5.
    phase_names = [p["phase"] for p in brief.interview_plan["phases"]]
    assert "self_intro" in phase_names
    assert "reverse_qa" in phase_names


def test_generate_brief_falls_back_on_bad_json():
    """Malformed LLM output → safe fallback brief, no exception."""
    mock_response = MagicMock()
    mock_response.text = "not even close to JSON"

    with patch.object(mod, "_mock_llm") as mock_llm:
        mock_llm.acomplete = AsyncMock(return_value=mock_response)
        brief = asyncio.run(generate_brief(resume_context="", jd_context=""))

    # The fallback has all 5 canonical phases.
    phase_names = [p["phase"] for p in brief.interview_plan["phases"]]
    assert set(phase_names) >= {"self_intro", "resume_deep_dive", "technical", "behavioral", "reverse_qa"}
    assert brief.min_turns == DEFAULT_TURN_BUDGETS["min"]


# ── run_director ─────────────────────────────────────────────────────────


def _valid_director_payload():
    return json.dumps({
        "action": "new_question",
        "phase": "technical",
        "spoken_response": "嗯，明白了。",
        "next_question": "什么是 Redis 持久化？",
        "topic": "redis_persistence",
        "answer_quality": {"level": "partial", "reason": "略浅"},
        "state_update": {
            "covered_topics_add": ["redis_basics"],
            "weak_topics_add": [],
            "strong_topics_add": [],
            "phase_should_advance": False,
        },
        "should_finish": False,
    })


def test_run_director_first_attempt_success():
    state = {
        "follow_up_depth": 0,
        "max_turns": 14,
        "turn_count": 5,
        "cacheable_prefix": "prefix",
        "interview_plan": {"phases": []},
        "phase_progress": {},
        "qa_history": [],
        "covered_topics": [],
        "weak_topics": [],
        "strong_topics": [],
    }
    mock_response = MagicMock()
    mock_response.text = _valid_director_payload()

    with patch.object(mod, "_mock_llm") as mock_llm:
        mock_llm.acomplete = AsyncMock(return_value=mock_response)
        result = asyncio.run(run_director(state, "我用过 Redis 做缓存"))

    assert isinstance(result, DirectorOutput)
    assert result.action == "new_question"
    assert result.topic == "redis_persistence"
    # Director should be called exactly once when validation passes immediately.
    assert mock_llm.acomplete.await_count == 1


def test_run_director_retries_on_invalid_json_then_succeeds():
    state = {
        "follow_up_depth": 0,
        "max_turns": 14,
        "turn_count": 5,
        "cacheable_prefix": "prefix",
        "interview_plan": {"phases": []},
        "phase_progress": {},
        "qa_history": [],
    }

    bad = MagicMock(); bad.text = "not json"
    good = MagicMock(); good.text = _valid_director_payload()

    with patch.object(mod, "_mock_llm") as mock_llm:
        mock_llm.acomplete = AsyncMock(side_effect=[bad, good])
        result = asyncio.run(run_director(state, "ans"))

    assert result.action == "new_question"
    assert mock_llm.acomplete.await_count == 2


def test_run_director_raises_after_max_retries():
    """If every attempt fails validation, raises DirectorRetryExhausted."""
    state = {
        "follow_up_depth": 0,
        "max_turns": 14,
        "turn_count": 5,
        "cacheable_prefix": "prefix",
        "interview_plan": {"phases": []},
        "phase_progress": {},
        "qa_history": [],
    }

    bad = MagicMock()
    bad.text = "still not json"

    with patch.object(mod, "_mock_llm") as mock_llm:
        mock_llm.acomplete = AsyncMock(return_value=bad)
        with pytest.raises(DirectorRetryExhausted):
            asyncio.run(run_director(state, "ans"))

    # Should have tried MAX_DIRECTOR_RETRIES + 1 times.
    assert mock_llm.acomplete.await_count == mod.MAX_DIRECTOR_RETRIES + 1
