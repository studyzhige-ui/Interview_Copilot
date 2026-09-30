"""Plan and generate turns for a mock interview.

One model call at interview start creates stage-specific guidance from the
resume and JD. Each candidate answer then generates the next interviewer line
from the frozen guidance and conversation history. A completed but malformed
model response can be repaired once; ambiguous transport failures are not
retried. Question counts do not drive stage progression.

Post-interview scoring remains in ``InterviewAnalysisOrchestrator``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from app.interviews.domain.specification import (
    InterviewSpecification,
    resolve_specification,
)

from app.core.context_budget import ContextCapacityError, RequestBudget, request_tokens

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


def _base_stages(spec: InterviewSpecification | None = None) -> list[dict[str, str]]:
    keys = resolve_specification(spec).stage_keys
    return [dict(stage) for stage in BASE_INTERVIEW_STAGES if stage["key"] in keys]


def build_prefix(
    resume_context: str,
    jd_context: str,
    style: str,
    *,
    specification: dict | InterviewSpecification | None = None,
) -> str:
    """Build the stable resume/JD/persona prefix shared by every turn."""
    resume = (resume_context or "").strip() or "（候选人未提供简历）"
    jd = (jd_context or "").strip() or "（未提供 JD）"
    spec = resolve_specification(specification)
    return (
        "<interview_specification>\n"
        + spec.model_dump_json()
        + "\n</interview_specification>\n"
        + MOCK_INTERVIEW_PREFIX.format(
            resume=resume,
            jd=jd,
            style=_style_brief(style),
        )
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
    """No valid interviewer turn was received; no transcript cursor may advance."""


def _clean_json(raw_text: str) -> dict[str, Any]:
    if not isinstance(raw_text, str) or len(raw_text) > 64_000:
        raise ValueError("Model JSON must be bounded text")
    raw = raw_text.strip()
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


def _guidance_from_response(
    data: dict[str, Any], keys: tuple[str, ...] | None = None
) -> dict[str, str]:
    raw = data.get("guidance")
    if not isinstance(raw, dict):
        raise ValueError("Plan output must contain a guidance object")
    guidance: dict[str, str] = {}
    expected = keys or tuple(_BASE_STAGE_KEYS)
    if set(raw) != set(expected):
        raise ValueError("Plan guidance must exactly match the frozen purpose stages")
    for key in expected:
        value = raw.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Plan guidance is missing stage {key}")
        if len(value.strip()) > 1200:
            raise ValueError(f"Plan guidance exceeds the stage limit: {key}")
        guidance[key] = value.strip()
    return guidance


def _guard_prompt(llm: Any, prompt: str, *, output: int) -> int:
    """Preserve full interview evidence or stop before dispatch; never clip it."""
    window = getattr(llm, "context_window", None)
    if type(window) is not int or window < 1:
        raise ContextCapacityError(
            "模拟面试模型未提供可验证的上下文上限，请检查模型配置。"
        )
    configured_output = getattr(llm, "max_tokens", None)
    if type(configured_output) is int and configured_output > 0:
        output = min(output, configured_output)
    budget = RequestBudget.resolve(window, output)
    if request_tokens([{"role": "user", "content": prompt}]) > budget.input_limit:
        raise ContextCapacityError(
            "模拟面试的完整资料与对话超过当前模型的上下文容量；未删减回答或发送模型请求。"
            "请选择容量足够的模型，或结束当前面试后使用较精简的资料重新开始。"
        )
    return budget.output


def _validated_turn(
    data: dict[str, Any], *, current_stage: str, stage_keys: list[str]
) -> NextTurn:
    message = data.get("message")
    if not isinstance(message, str) or not 1 <= len(message.strip()) <= 800:
        raise ValueError("message must be nonempty text of at most 800 characters")
    message = message.strip()
    if message.count("?") + message.count("？") > 2:
        raise ValueError(
            "message must focus on one question with at most two question marks"
        )
    index = stage_keys.index(current_stage)
    allowed = stage_keys[index : index + 2]
    stage = data.get("next_stage_key")
    if not isinstance(stage, str) or stage not in allowed:
        raise ValueError(
            "next_stage_key must be the current or immediately following stage"
        )
    ready = data.get("ready_to_finish")
    if type(ready) is not bool:
        raise ValueError("ready_to_finish must be a JSON boolean")
    return NextTurn(
        interviewer_message=message,
        next_stage_key=stage,
        is_ready_to_finish=ready
        and current_stage == stage_keys[-1]
        and stage == stage_keys[-1],
    )


def generate_plan(
    *,
    resume_context: str = "",
    jd_context: str = "",
    interviewer_style: str = "professional",
    user_id: str | None = None,
    llm: Any | None = None,
    specification: dict | InterviewSpecification | None = None,
) -> MockPlan:
    """Generate guidance for the program-selected purpose; the model cannot add stages."""
    spec = resolve_specification(specification)
    stages = _base_stages(spec)
    prompt = MOCK_INTERVIEW_PLAN_PROMPT.format(
        specification=spec.model_dump_json(),
        stage_contract=json.dumps(stages, ensure_ascii=False),
        resume=(resume_context or "").strip() or "（候选人未提供简历）",
        jd=(jd_context or "").strip() or "（未提供 JD）",
        style=_style_brief(interviewer_style),
    )
    if llm is None:
        llm = get_llm_for_role("primary", user_id=user_id)
    output_limit = _guard_prompt(llm, prompt, output=4096)
    response = llm.complete(
        prompt, response_format={"type": "json_object"}, max_tokens=output_limit
    )
    guidance = _guidance_from_response(_clean_json(response.text), spec.stage_keys)
    for stage in stages:
        stage["guidance"] = guidance[stage["key"]]
    formal = (interviewer_style or "").strip() in ("rigorous", "pressure")
    greeting = "您好，我们开始吧。" if formal else "你好，我们开始吧。"
    invitation = (
        "先请您结合目标岗位做一个简单的自我介绍。"
        if formal
        else "先请你结合目标岗位做一个简单的自我介绍。"
    )
    if spec.purpose == "project_deep_dive":
        invitation = (
            f"请先说明在“{spec.focus}”中你的具体职责，以及一个值得深入讨论的技术决策。"
        )
    elif spec.purpose == "focused_practice":
        invitation = f"围绕“{spec.focus}”，请先解释一个你认为最关键的概念或设计选择，并说明依据。"
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
        content = (message.get("content") or "").strip()
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
    llm: Any | None = None,
) -> NextTurn:
    """Generate one interviewer line from the frozen guidance and full history."""
    stage_keys = [stage["key"] for stage in stages]
    if (
        not stage_keys
        or len(stage_keys) != len(set(stage_keys))
        or current_stage_key not in stage_keys
    ):
        raise ValueError("Stored interview stage state is inconsistent")
    current_stage = current_stage_key
    current_index = stage_keys.index(current_stage)
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

    if llm is None:
        llm = get_llm_for_role("primary", user_id=user_id)
    last_error: Exception | None = None
    for attempt in range(2):
        correction = (
            "\n<retry_correction>上一完整输出违反结构契约："
            + str(last_error)
            + "。请重新输出完整 JSON；保持一个主要问题，不要解释或截断内容。</retry_correction>"
            if attempt
            else ""
        )
        request = prompt + correction
        output_limit = _guard_prompt(llm, request, output=1600)
        try:
            response = await llm.acomplete(
                request,
                response_format={"type": "json_object"},
                max_tokens=output_limit,
            )
        except Exception as exc:
            # No receipt was returned. A transport timeout may already be billed;
            # do not disguise a second request as malformed-output repair.
            raise NextTurnGenerationError(
                "未获得完整的面试官响应；已保留回答，未自动重发请求。"
            ) from exc
        try:
            return _validated_turn(
                _clean_json(response.text),
                current_stage=current_stage,
                stage_keys=stage_keys,
            )
        except (ValueError, TypeError, RecursionError) as exc:
            last_error = exc
            logger.warning(
                "Invalid completed mock response at attempt %d (%s)",
                attempt + 1,
                type(exc).__name__,
            )
    raise NextTurnGenerationError(
        "模型未生成符合契约的下一道问题；当前面试进度未推进。"
    ) from last_error


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
