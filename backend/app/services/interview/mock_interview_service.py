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

from app.rag.embeddings import mock_interview_llm as _mock_llm

logger = logging.getLogger(__name__)


# ── Interviewer personas ─────────────────────────────────────────────────

INTERVIEWER_STYLES: dict[str, str] = {
    "friendly": (
        "你是一位温和友善的面试官，给候选人充分的思考时间和适度的引导。"
        "肯定为主，不咄咄逼人；当候选人卡壳时给出温和的提示。"
    ),
    "professional": (
        "你是一位专业、就事论事的面试官。节奏标准，问题清晰，不带情绪色彩。"
        "回答到位就推进，模糊就追问一层。"
    ),
    "rigorous": (
        "你是一位严谨挑剔的面试官，会追究边界 case 和具体细节。"
        "追问比较尖锐，但保持职业；不允许笼统含糊的回答蒙混过去。"
    ),
    "pressure": (
        "你是一位高强度的压力面试官，连珠追问、质疑回答的细节和动机，模拟真实大厂压力面。"
        "保持专业边界，不羞辱不嘲讽；目的是看候选人在压力下的思路稳定性。"
    ),
}


def _style_brief(style: str | None) -> str:
    return INTERVIEWER_STYLES.get(
        (style or "professional").strip(), INTERVIEWER_STYLES["professional"]
    )


# ── Plan templates (phase 1: only "general") ─────────────────────────────
# Real interview business stages, not internal system phases. The stage list
# is frozen into ``mock_interview_runtime.plan_json`` at start so a later
# template change can't affect a started or finished run.

GENERAL_PLAN_TEMPLATE: list[dict[str, str]] = [
    {"key": "self_intro", "title": "自我介绍"},
    {"key": "resume_project_deep_dive", "title": "简历项目深挖"},
    {"key": "role_technical_assessment", "title": "岗位相关技术考察"},
    {"key": "candidate_questions", "title": "反问"},
]

PLAN_TEMPLATES: dict[str, list[dict[str, str]]] = {
    "general": GENERAL_PLAN_TEMPLATE,
}


def _template_stages(plan_template_key: str | None) -> list[dict[str, str]]:
    return PLAN_TEMPLATES.get((plan_template_key or "general").strip(), GENERAL_PLAN_TEMPLATE)


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
    return (
        "你是资深技术面试官。核心原则：认真听 → 基于材料判断 → "
        "接住对方刚说的话 → 决定追问 / 推进。每次只问一个清晰问题；"
        "不要书面化堆砌；不要一口气问多个。\n"
        "\n═════════ 候选人简历（全文） ═════════\n"
        f"{resume}\n"
        "\n═════════ 目标岗位 JD（全文） ═════════\n"
        f"{jd}\n"
        "\n═════════ 你的人设 ═════════\n"
        f"{_style_brief(style)}\n"
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
            {"key": str(s.get("key")), "title": str(s.get("title") or s.get("key"))}
            for s in stages
            if isinstance(s, dict) and s.get("key")
        ]
        if out:
            return out
    return GENERAL_PLAN_TEMPLATE


_NEXT_TURN_PROMPT = """{prefix}
## 本场面试阶段（按顺序）
{stage_list}

## 当前阶段
{current_stage}

## 最近对话
{recent_dialog}

## 候选人刚才的回答
{user_answer}

## 你的任务
作为面试官，自然地接住候选人刚才的回答，并给出下一句话。规则：
- 一段连贯口语，先简短承接，再问下一个问题；只问一个问题。
- 在当前阶段聊够了就推进到下一个阶段（stage_key 用下一个阶段的 key）；否则保持当前阶段。
- 进入「反问」阶段（candidate_questions）时，邀请候选人提问，并认真回答其问题。
- 反问阶段也聊完、整场覆盖充分时，把 ready_to_finish 设为 true，并说一句收尾的话。
- 候选人放弃某题（说"不知道/跳过"）时温和带过，不要纠缠。

严格输出 JSON：
{{
  "message": "你作为面试官说出口的下一句话",
  "stage_key": "{stage_keys_hint}",
  "ready_to_finish": false
}}
"""


async def generate_next_turn(
    *,
    prefix: str,
    stages: list[dict[str, str]],
    current_stage_key: str,
    recent_messages: list[dict[str, str]],
    user_answer: str,
) -> NextTurn:
    """One LLM call → the next interviewer line + stage + finish signal.

    No retry, no constraint validation. On a parse failure the interview keeps
    moving with a safe generic prompt rather than 503-ing the candidate.
    """
    stage_keys = [s["key"] for s in stages]
    stage_list = "\n".join(
        f"  {i + 1}. {s['key']} — {s.get('title', s['key'])}" for i, s in enumerate(stages)
    )
    recent_dialog = _recent_dialog_block(recent_messages)

    prompt = _NEXT_TURN_PROMPT.format(
        prefix=prefix,
        stage_list=stage_list,
        current_stage=current_stage_key or (stage_keys[0] if stage_keys else "self_intro"),
        recent_dialog=recent_dialog,
        user_answer=(user_answer or "").strip() or "（候选人沉默）",
        stage_keys_hint=" | ".join(stage_keys),
    )

    try:
        response = await _mock_llm.acomplete(prompt, response_format={"type": "json_object"})
        data = _clean_json(str(response.text))
    except Exception as exc:  # noqa: BLE001 — any failure: keep the interview moving
        logger.warning("generate_next_turn failed (non-fatal, advancing safely): %s", exc)
        return NextTurn(
            interviewer_message="好的，我们继续。能再展开讲讲你刚才提到的点吗？",
            next_stage_key=current_stage_key or (stage_keys[0] if stage_keys else "self_intro"),
            is_ready_to_finish=False,
        )

    message = str(data.get("message") or "").strip()
    if not message:
        message = "好的，我们继续。能再多说一些吗？"

    next_stage = str(data.get("stage_key") or "").strip()
    if next_stage not in stage_keys:
        next_stage = current_stage_key or (stage_keys[0] if stage_keys else "self_intro")

    return NextTurn(
        interviewer_message=message,
        next_stage_key=next_stage,
        is_ready_to_finish=bool(data.get("ready_to_finish", False)),
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
