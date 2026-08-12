"""Plan and generate turns for a mock interview.

One model call at interview start creates stage-specific guidance from the
resume and JD. Each candidate answer then generates the next interviewer line
from the frozen guidance and conversation history. A malformed or transient
model response is retried once; question counts do not drive stage progression.

Post-interview scoring remains in ``InterviewAnalysisOrchestrator``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from app.prompts.interview import (
    INTERVIEWER_STYLES,
    MOCK_INTERVIEW_NEXT_TURN_PROMPT,
    MOCK_INTERVIEW_PLAN_PROMPT,
    MOCK_INTERVIEW_PREFIX,
)

logger = logging.getLogger(__name__)


def get_llm_for_role(*args, **kwargs):
    """Load the LLM adapter only when an interview actually needs a model."""
    from app.core.llm_client_factory import get_llm_for_role as factory

    return factory(*args, **kwargs)


# Stable business stages. The planning model personalizes ``guidance`` only;
# stable keys keep runtime transitions, progress UI and review attribution
# deterministic.
BASE_INTERVIEW_STAGES: list[dict[str, str]] = [
    {
        "key": "self_intro",
        "title": "自我介绍",
        "phase": "self_intro",
        "guidance": "判断候选人与目标岗位的整体匹配，并从回答中发现后续值得验证的经历。",
    },
    {
        "key": "resume_project_deep_dive",
        "title": "简历项目深挖",
        "phase": "resume_deep_dive",
        "guidance": "选择与岗位最相关的项目，验证候选人的个人贡献、技术决策、结果和取舍。",
    },
    {
        "key": "role_technical_assessment",
        "title": "岗位相关技术考察",
        "phase": "technical",
        "guidance": "围绕岗位关键能力选择有代表性的问题，不按语言、框架或知识目录逐项穷举。",
    },
    {
        "key": "candidate_questions",
        "title": "反问",
        "phase": "reverse_qa",
        "guidance": "邀请并回答候选人的合理问题；资料不足时坦诚说明，不编造公司或团队信息。",
    },
]

STAGE_TO_PHASE: dict[str, str] = {
    stage["key"]: stage["phase"] for stage in BASE_INTERVIEW_STAGES
}
_BASE_STAGE_KEYS = [stage["key"] for stage in BASE_INTERVIEW_STAGES]


def _style_brief(style: str | None) -> str:
    return INTERVIEWER_STYLES.get(
        (style or "professional").strip(), INTERVIEWER_STYLES["professional"]
    )


def _base_stages() -> list[dict[str, str]]:
    return [dict(stage) for stage in BASE_INTERVIEW_STAGES]


def build_prefix(resume_context: str, jd_context: str, style: str) -> str:
    """Build the stable resume/JD/persona prefix shared by every turn."""
    resume = (resume_context or "").strip() or "（候选人未提供简历）"
    jd = (jd_context or "").strip() or "（未提供 JD）"
    return MOCK_INTERVIEW_PREFIX.format(
        resume=resume,
        jd=jd,
        style=_style_brief(style),
    )


def prefix_hash(prefix: str) -> str:
    return hashlib.sha256(prefix.encode("utf-8")).hexdigest()[:16]


def detect_response_language(text: str) -> str:
    """Choose the candidate's dominant conversational language."""
    value = (text or "").strip()
    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", value))
    english_words = len(re.findall(r"[A-Za-z]{2,}", value))
    first = re.search(r"[A-Za-z\u4e00-\u9fff]", value)
    first_char = first.group(0) if first else ""
    if "\u4e00" <= first_char <= "\u9fff" and cjk_count >= 2:
        return "zh"
    if first_char.isascii() and first_char.isalpha() and english_words >= 3:
        return "en"
    if cjk_count >= 4:
        return "zh"
    return "en" if english_words >= 3 else "zh"


@dataclass
class MockPlan:
    stages: list[dict[str, str]]
    opening_message: str
    first_stage_key: str


@dataclass(frozen=True)
class NextTurn:
    interviewer_message: str
    next_stage_key: str
    is_ready_to_finish: bool


class NextTurnGenerationError(RuntimeError):
    """The interviewer model failed twice without producing a valid turn."""


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


def _guidance_from_response(data: dict[str, Any]) -> dict[str, str]:
    raw = data.get("guidance")
    if not isinstance(raw, dict):
        raise ValueError("Plan output must contain a guidance object")
    guidance: dict[str, str] = {}
    for key in _BASE_STAGE_KEYS:
        value = str(raw.get(key) or "").strip()
        if not value:
            raise ValueError(f"Plan guidance is missing stage {key}")
        guidance[key] = value[:1200]
    return guidance


def generate_plan(
    *,
    resume_context: str = "",
    jd_context: str = "",
    interviewer_style: str = "professional",
    user_id: str | None = None,
) -> MockPlan:
    """Generate and freeze personalized guidance for the stable four stages."""
    prompt = MOCK_INTERVIEW_PLAN_PROMPT.format(
        resume=(resume_context or "").strip() or "（候选人未提供简历）",
        jd=(jd_context or "").strip() or "（未提供 JD）",
        style=_style_brief(interviewer_style),
    )
    llm = get_llm_for_role("primary", user_id=user_id)
    response = llm.complete(prompt, response_format={"type": "json_object"})
    guidance = _guidance_from_response(_clean_json(str(response.text)))

    stages = _base_stages()
    for stage in stages:
        stage["guidance"] = guidance[stage["key"]]
    formal = (interviewer_style or "").strip() in ("rigorous", "pressure")
    greeting = "您好，我们开始吧。" if formal else "你好，我们开始吧。"
    invitation = (
        "先请您结合目标岗位做一个简单的自我介绍。"
        if formal
        else "先请你结合目标岗位做一个简单的自我介绍。"
    )
    return MockPlan(
        stages=stages,
        opening_message=f"{greeting}{invitation}",
        first_stage_key=stages[0]["key"],
    )


def _conversation_history_block(messages: list[dict[str, str]]) -> str:
    if not messages:
        return "（暂无历史对话）"
    lines: list[str] = []
    for message in messages:
        role = message.get("role") or ""
        who = "面试官" if role.lower().startswith(("assistant", "agent")) else "候选人"
        content = (message.get("content") or "").strip()[:2000]
        if content:
            lines.append(f"  {who}: {content}")
    return "\n".join(lines) or "（暂无历史对话）"


async def generate_next_turn(
    *,
    prefix: str,
    stages: list[dict[str, str]],
    current_stage_key: str,
    conversation_messages: list[dict[str, str]],
    user_answer: str,
    user_id: str | None = None,
    length_warning_active: bool = False,
) -> NextTurn:
    """Generate one interviewer line from the frozen guidance and full history."""
    stage_keys = [stage["key"] for stage in stages]
    current_stage = (
        current_stage_key
        if current_stage_key in stage_keys
        else (stage_keys[0] if stage_keys else "self_intro")
    )
    current_index = (
        stage_keys.index(current_stage) if current_stage in stage_keys else 0
    )
    stage_list = "\n".join(
        f"  {index + 1}. {stage['key']} — {stage.get('title', stage['key'])}\n"
        f"     guidance: {stage.get('guidance') or '围绕当前阶段目标选择有代表性的问题。'}"
        for index, stage in enumerate(stages)
    )
    next_stage = stages[current_index + 1] if current_index + 1 < len(stages) else None
    prompt = MOCK_INTERVIEW_NEXT_TURN_PROMPT.format(
        prefix=prefix,
        stage_list=stage_list,
        current_stage=current_stage,
        response_language=(
            "简体中文（英文技术术语原样保留）"
            if detect_response_language(user_answer) == "zh"
            else "English (preserve Chinese technical terms as written)"
        ),
        length_warning_active="true" if length_warning_active else "false",
        pacing_instruction=(
            "警戒提醒已触发：先判断 latest_answer 是否实质回答了面试官上一问。"
            + (
                "若已回答，下一句话必须进入紧邻阶段 "
                f"{next_stage['key']}（{next_stage.get('title', next_stage['key'])}），"
                f"问题必须服务于该阶段 guidance：{next_stage.get('guidance', '')}。"
                "不得选择 latest_answer 中的另一细节继续深挖，也不得只改 next_stage_key 而继续旧阶段问题；"
                if next_stage is not None
                else "当前已是最后阶段；"
            )
            + "若未回答清楚，只允许针对原问题澄清一次。不要直接宣布面试结束。"
            if length_warning_active
            else "警戒提醒未触发：按照阶段 guidance 和信息增益自然推进。"
        ),
        conversation_history=_conversation_history_block(conversation_messages),
        user_answer=(user_answer or "").strip() or "（候选人沉默）",
        stage_keys_hint=" | ".join(stage_keys),
    )

    llm = get_llm_for_role("primary", user_id=user_id)
    last_error: Exception | None = None
    data: dict[str, Any] | None = None
    for attempt in range(2):
        try:
            response = await llm.acomplete(
                (
                    prompt
                    if attempt == 0
                    else prompt
                    + "\n<retry_correction>上一输出不符合单一问题契约。请只保留一个判断点，全文最多两个问号。</retry_correction>"
                ),
                response_format={"type": "json_object"},
            )
            candidate = _clean_json(str(response.text))
            candidate_message = str(candidate.get("message") or "").strip()
            question_marks = candidate_message.count("?") + candidate_message.count(
                "？"
            )
            if not candidate_message or question_marks > 2:
                raise ValueError(
                    "interviewer message violates the single-question contract"
                )
            data = candidate
            break
        except Exception as exc:  # noqa: BLE001 - normalized below
            last_error = exc
            logger.warning(
                "generate_next_turn attempt %d failed: %s",
                attempt + 1,
                exc,
            )
    if data is None:
        raise NextTurnGenerationError("无法生成下一道面试问题") from last_error

    message = str(data["message"]).strip()[:800]

    allowed_stages = {current_stage}
    if current_index + 1 < len(stage_keys):
        allowed_stages.add(stage_keys[current_index + 1])
    next_stage = str(data.get("next_stage_key") or "").strip()
    if next_stage not in allowed_stages:
        next_stage = current_stage

    # Entering the final stage is not the same as completing it. The candidate
    # must first have a chance to ask questions.
    in_final_stage = bool(stage_keys) and current_stage == stage_keys[-1]
    stays_in_final_stage = in_final_stage and next_stage == stage_keys[-1]
    ready_to_finish = data.get("ready_to_finish") is True and stays_in_final_stage

    return NextTurn(
        interviewer_message=message,
        next_stage_key=next_stage,
        is_ready_to_finish=ready_to_finish,
    )


__all__ = [
    "BASE_INTERVIEW_STAGES",
    "STAGE_TO_PHASE",
    "MockPlan",
    "NextTurn",
    "NextTurnGenerationError",
    "build_prefix",
    "detect_response_language",
    "generate_next_turn",
    "generate_plan",
    "prefix_hash",
]
