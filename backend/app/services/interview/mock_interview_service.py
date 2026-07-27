"""Mock interview conducting layer (target architecture, RFC §6.4).

No "Runtime Director", no retry loop, no hard-constraint validators. A mock
interview is driven by:

  1. A frozen ``plan_json`` snapshot of the chosen template's business stages
     (self_intro → resume_project_deep_dive → role_technical_assessment →
     candidate_questions). Template edits never affect a started run.
  2. A cacheable prefix (resume + JD + persona) rebuilt from the interview
     record's immutable snapshots on each turn.
  3. One LLM call per answer (``generate_next_turn``) that, given the plan,
     the current stage and recent messages, produces the next interviewer
     line, the (possibly advanced) stage, and whether the interview is ready
     to finish. The server does not fabricate questions and does not retry.

Post-interview scoring is handled by the unified
``InterviewAnalysisOrchestrator`` (shared with the upload-audio debrief path);
this module is only the conducting layer.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any

from app.core.llm_client_factory import get_llm_for_role
from app.prompts.interview import (
    INTERVIEWER_STYLES,
    MOCK_INTERVIEW_NEXT_TURN_PROMPT,
    MOCK_INTERVIEW_PREFIX,
)

logger = logging.getLogger(__name__)


# ── Interviewer personas ─────────────────────────────────────────────────


def _style_brief(style: str | None) -> str:
    return INTERVIEWER_STYLES.get(
        (style or "professional").strip(), INTERVIEWER_STYLES["professional"]
    )


# ── Plan templates (phase 1: only "general") ─────────────────────────────
# Real interview business stages, not internal system phases. The stage list
# is frozen into ``mock_interview_runtime.plan_json`` at start so a later
# template change can't affect a started or finished run.

# Per-question truncation in the asked-question inventory (chars) — also
# interpolated into the prompt so the claim can't drift from the slice.
_ASKED_QUESTION_TRUNC = 40

# ``phase`` maps each stage onto the analysis-report vocabulary
# (interview_analysis_service._PHASE_NAME_MAP) — defined HERE, next to the
# stage keys, so adding a stage can't silently degrade its review
# attribution to "general".
GENERAL_PLAN_TEMPLATE: list[dict[str, str]] = [
    {"key": "self_intro", "title": "自我介绍", "phase": "self_intro"},
    {
        "key": "resume_project_deep_dive",
        "title": "简历项目深挖",
        "phase": "resume_deep_dive",
    },
    {
        "key": "role_technical_assessment",
        "title": "岗位相关技术考察",
        "phase": "technical",
    },
    {"key": "candidate_questions", "title": "反问", "phase": "reverse_qa"},
]


PLAN_TEMPLATES: dict[str, list[dict[str, str]]] = {
    "general": GENERAL_PLAN_TEMPLATE,
}

# stage_key → analysis phase, derived from the templates (single source —
# the review pipeline imports this instead of keeping its own copy).
STAGE_TO_PHASE: dict[str, str] = {
    s["key"]: s.get("phase", "general")
    for stages in PLAN_TEMPLATES.values()
    for s in stages
}


def _template_stages(plan_template_key: str | None) -> list[dict[str, str]]:
    return PLAN_TEMPLATES.get(
        (plan_template_key or "general").strip(), GENERAL_PLAN_TEMPLATE
    )


# ── Cacheable prefix ─────────────────────────────────────────────────────


def build_prefix(resume_context: str, jd_context: str, style: str) -> str:
    """Verbatim-stable prefix that every per-turn LLM call starts with.

    Deterministic w.r.t. its inputs (no timestamps / random whitespace) so the
    DeepSeek prompt cache can hit on the prefix tokens. Rebuilt each turn from
    the interview record's immutable resume/JD snapshots, so it stays stable
    for the life of the run even if the user later edits the source resume.
    """
    resume = (resume_context or "").strip() or "（候选人未提供简历）"
    jd = (jd_context or "").strip() or "（未提供 JD）"
    return MOCK_INTERVIEW_PREFIX.format(
        resume=resume,
        jd=jd,
        style=_style_brief(style),
    )


def prefix_hash(prefix: str) -> str:
    return hashlib.sha256(prefix.encode("utf-8")).hexdigest()[:16]


# ── Output dataclasses ───────────────────────────────────────────────────


@dataclass
class MockPlan:
    """Result of ``generate_plan`` — what mock-start freezes + shows."""

    template_key: str
    stages: list[dict[str, str]]
    plan_json: str
    opening_message: str
    first_stage_key: str


@dataclass
class NextTurn:
    """Result of ``generate_next_turn`` — the next interviewer line."""

    interviewer_message: str
    next_stage_key: str
    is_ready_to_finish: bool
    # Set by mock_flow.submit_answer after persisting the message — the FE
    # echoes it back with the next answer as the concurrency token (MOCK-3).
    question_message_id: int | None = None


# ── JSON helper ──────────────────────────────────────────────────────────


def _clean_json(raw_text: str) -> dict[str, Any]:
    raw = (raw_text or "").strip()
    if raw.startswith("```json"):
        raw = raw[7:]
    elif raw.startswith("```"):
        raw = raw[3:]
    if raw.endswith("```"):
        raw = raw[:-3]
    data = json.loads(raw.strip())
    if not isinstance(data, dict):
        raise ValueError("Top-level JSON must be an object")
    return data


# ── Public API ───────────────────────────────────────────────────────────


def generate_plan(
    *,
    resume_context: str = "",
    jd_context: str = "",
    interviewer_style: str = "professional",
    plan_template_key: str = "general",
) -> MockPlan:
    """Freeze the plan + opening line for a new run.

    Deterministic (no LLM): the opening greeting + self-intro invitation are
    style-flavored but fixed, so mock-start is fast and never fails on a model
    hiccup. The per-turn LLM does the actual interviewing work. ``resume_context``
    / ``jd_context`` are accepted for forward compatibility (a future template
    may tailor stage goals) but the phase-1 general template is static.
    """
    stages = _template_stages(plan_template_key)
    plan_json = json.dumps({"stages": stages}, ensure_ascii=False)
    formal = (interviewer_style or "").strip() in ("rigorous", "pressure")
    greeting = "您好，我们开始吧。" if formal else "你好，我们开始吧。"
    invite = (
        "先请您做一个简单的自我介绍。" if formal else "先请你做一个简单的自我介绍。"
    )
    return MockPlan(
        template_key=(plan_template_key or "general").strip(),
        stages=stages,
        plan_json=plan_json,
        opening_message=f"{greeting}{invite}",
        first_stage_key=stages[0]["key"],
    )


def stages_from_plan_json(plan_json: str | None) -> list[dict[str, str]]:
    """Parse the frozen stage list back out of ``runtime.plan_json``."""
    if not plan_json:
        return GENERAL_PLAN_TEMPLATE
    try:
        data = json.loads(plan_json)
    except (json.JSONDecodeError, TypeError):
        return GENERAL_PLAN_TEMPLATE
    stages = data.get("stages") if isinstance(data, dict) else None
    if isinstance(stages, list) and stages:
        out = [
            # ``phase`` (review attribution, MOCK-8) survives the round-trip
            # for plans frozen after Phase 5; older plans simply omit it.
            {
                "key": str(s.get("key")),
                "title": str(s.get("title") or s.get("key")),
                **({"phase": str(s["phase"])} if s.get("phase") else {}),
            }
            for s in stages
            if isinstance(s, dict) and s.get("key")
        ]
        if out:
            return out
    return GENERAL_PLAN_TEMPLATE


async def generate_next_turn(
    *,
    prefix: str,
    stages: list[dict[str, str]],
    current_stage_key: str,
    recent_messages: list[dict[str, str]],
    user_answer: str,
    user_id: str | None = None,
    asked_questions: list[str] | None = None,
    questions_in_current_stage: int = 0,
) -> NextTurn:
    """One LLM call → the next interviewer line + stage + finish signal.

    No retry, no constraint validation. On a parse failure the interview keeps
    moving with a safe generic prompt rather than 503-ing the candidate.
    """
    stage_keys = [s["key"] for s in stages]
    stage_list = "\n".join(
        f"  {i + 1}. {s['key']} — {s.get('title', s['key'])}"
        for i, s in enumerate(stages)
    )
    recent_dialog = _recent_dialog_block(recent_messages)

    # MOCK-6: the recent-8 window only remembers ~4 turns; a 20-turn
    # interview repeated earlier questions. The full asked-question index
    # (40 chars each) keeps the prompt bounded while covering the whole run.
    asked_block = (
        "\n".join(
            f"  {i + 1}. {q[:_ASKED_QUESTION_TRUNC]}"
            for i, q in enumerate(asked_questions or [])
        )
        or "（暂无）"
    )
    prompt = MOCK_INTERVIEW_NEXT_TURN_PROMPT.format(
        prefix=prefix,
        stage_list=stage_list,
        current_stage=current_stage_key
        or (stage_keys[0] if stage_keys else "self_intro"),
        recent_dialog=recent_dialog,
        asked_questions=asked_block,
        asked_trunc=_ASKED_QUESTION_TRUNC,
        questions_in_current_stage=questions_in_current_stage,
        user_answer=(user_answer or "").strip() or "（候选人沉默）",
        stage_keys_hint=" | ".join(stage_keys),
    )

    try:
        llm = get_llm_for_role("primary", user_id=user_id)
        response = await llm.acomplete(prompt, response_format={"type": "json_object"})
        data = _clean_json(str(response.text))
    except Exception as exc:  # noqa: BLE001 — any failure: keep the interview moving
        logger.warning(
            "generate_next_turn failed (non-fatal, advancing safely): %s", exc
        )
        return NextTurn(
            interviewer_message="好的，我们继续。能再展开讲讲你刚才提到的点吗？",
            next_stage_key=current_stage_key
            or (stage_keys[0] if stage_keys else "self_intro"),
            is_ready_to_finish=False,
        )

    message = str(data.get("message") or "").strip()[:800]
    if not message:
        message = "好的，我们继续。能再多说一些吗？"

    current_stage = (
        current_stage_key
        if current_stage_key in stage_keys
        else (stage_keys[0] if stage_keys else "self_intro")
    )
    current_index = (
        stage_keys.index(current_stage) if current_stage in stage_keys else 0
    )
    allowed_stages = {current_stage}
    if current_index + 1 < len(stage_keys):
        allowed_stages.add(stage_keys[current_index + 1])

    # The model proposes a transition; the domain layer owns the state
    # machine. Reject backward moves and stage jumps even when the JSON is
    # otherwise valid.
    next_stage = str(data.get("stage_key") or "").strip()
    if next_stage not in allowed_stages:
        next_stage = current_stage

    # Only the final stage may end the interview. Use an actual JSON boolean:
    # bool("false") is True in Python and previously allowed malformed model
    # output to end a run early.
    ready_to_finish = (
        data.get("ready_to_finish") is True
        and bool(stage_keys)
        and next_stage == stage_keys[-1]
    )

    return NextTurn(
        interviewer_message=message,
        next_stage_key=next_stage,
        is_ready_to_finish=ready_to_finish,
    )


def _recent_dialog_block(recent_messages: list[dict[str, str]], n: int = 8) -> str:
    if not recent_messages:
        return "（首轮，无历史）"
    lines: list[str] = []
    for m in recent_messages[-n:]:
        role = m.get("role") or ""
        who = "面试官" if role.lower().startswith(("assistant", "agent")) else "候选人"
        content = (m.get("content") or "").strip()[:600]
        if content:
            lines.append(f"  {who}: {content}")
    return "\n".join(lines) or "（首轮，无历史）"


# ── Facade (preserves ``mock_interview_service.X`` import style) ──────────


class MockInterviewService:
    INTERVIEWER_STYLES = INTERVIEWER_STYLES
    PLAN_TEMPLATES = PLAN_TEMPLATES

    @staticmethod
    def build_prefix(resume_context: str, jd_context: str, style: str) -> str:
        return build_prefix(resume_context, jd_context, style)

    @staticmethod
    def prefix_hash(prefix: str) -> str:
        return prefix_hash(prefix)

    @staticmethod
    def generate_plan(
        *,
        resume_context: str = "",
        jd_context: str = "",
        interviewer_style: str = "professional",
        plan_template_key: str = "general",
    ) -> MockPlan:
        return generate_plan(
            resume_context=resume_context,
            jd_context=jd_context,
            interviewer_style=interviewer_style,
            plan_template_key=plan_template_key,
        )

    @staticmethod
    async def generate_next_turn(
        *,
        prefix: str,
        stages: list[dict[str, str]],
        current_stage_key: str,
        recent_messages: list[dict[str, str]],
        user_answer: str,
    ) -> NextTurn:
        return await generate_next_turn(
            prefix=prefix,
            stages=stages,
            current_stage_key=current_stage_key,
            recent_messages=recent_messages,
            user_answer=user_answer,
        )


mock_interview_service = MockInterviewService()


__all__ = [
    "INTERVIEWER_STYLES",
    "PLAN_TEMPLATES",
    "GENERAL_PLAN_TEMPLATE",
    "MockPlan",
    "NextTurn",
    "build_prefix",
    "prefix_hash",
    "generate_plan",
    "generate_next_turn",
    "stages_from_plan_json",
    "mock_interview_service",
]
