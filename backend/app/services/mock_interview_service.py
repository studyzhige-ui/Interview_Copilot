"""Mock interview orchestration service.

Drives an in-flight interview:
  1. generate_plan()                  — LLM reads resume → phased plan
  2. get_current_question()           — returns the current question
  3. generate_interviewer_response()  — natural reply (no scoring)
  4. advance_state()                  — move to next question or follow-up

Post-interview scoring is handled by the unified
``InterviewAnalysisOrchestrator`` (see services/interview/analysis_orchestrator).
There is no longer a synchronous ``batch_evaluate`` path — finish dispatches the
orchestrator asynchronously.

Interviewer persona is parameterised by an ``interviewer_style`` enum
(`friendly` / `professional` / `rigorous` / `pressure`) that the user picks in
MockSetup. The style controls tone only; JD-inferred seniority controls depth
(handled inside the prompt itself).
"""

import json
import logging
import math
from typing import Any

from app.rag.embeddings import agent_fast_llm
from app.services.interview.structured_extraction import (
    format_jd_pool,
    format_resume_pool,
    fundamentals_quota_for,
)

logger = logging.getLogger(__name__)


# ── Interviewer style ────────────────────────────────────────────────────

INTERVIEWER_STYLES: dict[str, str] = {
    "friendly": (
        "你是一位温和友善的面试官，喜欢给候选人充分的思考时间和适度的引导。"
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
    return INTERVIEWER_STYLES.get((style or "professional").strip(), INTERVIEWER_STYLES["professional"])


# ── Plan generation ──────────────────────────────────────────────────────

PLAN_PROMPT_GROUNDED = """{style_brief}

你正在为这位候选人量身定制一场面试。简历和 JD 已经被结构化为带 ref_id 的"证据池"。
**除了允许的八股配额外，每道生成的题目都必须挂载 grounding_refs，且 ref 必须来自下面给出的池子。**
缺乏 grounding 的通用八股不允许出现（除非显式标 fundamentals）。

【简历证据池】
{resume_pool}

【JD 要求池】
{jd_pool}

【阶段约束】
- self_intro: 1 题，grounding_refs 可为空数组（开场不需要 grounding）。
- resume_deep_dive: 2-4 题，每题 grounding_refs 必须包含至少一个 exp_*.h* 或 proj_*.h*。
- technical: 3-4 题，按 seniority 控制八股配额：本场允许最多 {fundamentals_max} 道八股题；
  八股题的 grounding_refs 形如 ["fundamentals:<topic>"]（topic 例如 "gc"、"tcp"、"index"）；
  其余题必须扎根 must_have / nice_to_have（req_* / nice_*）或简历中相关技术栈，
  并尽量自然联系到简历的 exp_*.h*。
- behavioral: 1-2 题，每题 grounding_refs 可为 ["resp_*"] 或与团队/影响力相关的 exp_*.h*。
- reverse_qa: 1 题（占位语），grounding_refs 为空数组。

【其他要求】
- 每个问题要具体、紧贴 grounding_refs 的实质内容，避免空泛。
- 难度曲线遵循 warm_up → core → stretch（同一阶段内由浅到深）。
- 不要重复同一 ref_id 超过两次。

输出严格 JSON：
{{
  "phases": [
    {{
      "phase_id": "self_intro",
      "phase_name": "自我介绍",
      "questions": [
        {{ "question": "...", "grounding_refs": [] }}
      ]
    }},
    {{
      "phase_id": "technical",
      "phase_name": "技术深度",
      "questions": [
        {{ "question": "你提到把推荐系统 QPS 从 3k 提到 12k —— 在分布式部署下你如何保证特征数据一致性？",
           "grounding_refs": ["exp_1.h1", "req_2"] }},
        {{ "question": "讲讲 Go 的 GC 三色标记。",
           "grounding_refs": ["fundamentals:gc"] }}
      ]
    }}
  ]
}}"""

NO_RESUME_PLAN_PROMPT = """{style_brief}

候选人没有提供简历，请生成一份通用技术面试计划。

包含阶段：self_intro(1题), technical(3题, 通用后端/前端基础, 全部标为 fundamentals),
behavioral(1题), reverse_qa(1题)。

每题输出 grounding_refs；通用八股题挂 ["fundamentals:<topic>"]。

输出严格 JSON：
{{
  "phases": [
    {{ "phase_id": "self_intro", "phase_name": "自我介绍",
       "questions": [{{ "question": "请介绍你自己。", "grounding_refs": [] }}] }}
  ]
}}"""


# ── Interviewer response prompt ──────────────────────────────────────────

INTERVIEWER_RESPONSE_PROMPT = """{style_brief}

你正在面试，请根据候选人的回答给出面试官的自然回应（不要给出评分或反馈）。

当前阶段：{phase_id}
当前问题：{question}
候选人回答：{answer}
{resume_context_section}
之前的对话：
{qa_history_text}

规则：
- 像真正的面试官一样自然回应；保持你设定的风格一致。
- 根据回答质量决定下一步：
  - 回答不够深入或有疑点 → action="follow_up"，并提出一个具体的追问；
  - 回答充分 → action="next_question"，自然过渡到下一题；
  - 阶段所有题问完 → action="next_question"。
- 回应要简短自然（1-3 句话），像真实对话。
- 不要重复用户已经回答清楚的内容。

输出 JSON：
{{
  "response": "面试官的自然回应文本",
  "action": "follow_up" 或 "next_question",
  "follow_up_question": "追问的问题（仅当 action 为 follow_up 时填写，否则为空）"
}}"""


class MockInterviewService:
    """Orchestrates a mock interview session."""

    # ── Plan generation ──────────────────────────────────────────────

    async def generate_plan(
        self,
        resume_context: str = "",
        *,
        jd_context: str = "",
        resume_evidence: dict[str, Any] | None = None,
        jd_requirements: dict[str, Any] | None = None,
        interviewer_style: str = "professional",
    ) -> dict[str, Any]:
        """Generate a structured interview plan.

        If structured resume_evidence / jd_requirements are passed in, the
        prompt switches to the grounded variant — every question must declare
        grounding_refs against the evidence pools. Without structured inputs
        we fall back to a generic plan (no grounding, generic questions).
        """
        style_brief = _style_brief(interviewer_style)
        has_evidence = bool(
            resume_evidence and (resume_evidence.get("experiences") or resume_evidence.get("projects"))
        )
        has_jd = bool(jd_requirements and (jd_requirements.get("must_have") or jd_requirements.get("responsibilities")))

        if has_evidence or has_jd:
            seniority = (jd_requirements or {}).get("seniority", "mid") if jd_requirements else "mid"
            # Cap technical-phase fundamentals count by seniority-based quota.
            # Plan asks for 3-4 technical questions; we permit ceil(quota * 4).
            fundamentals_max = max(0, math.ceil(fundamentals_quota_for(seniority) * 4))
            prompt = PLAN_PROMPT_GROUNDED.format(
                style_brief=style_brief,
                resume_pool=format_resume_pool(resume_evidence or {}) or "（候选人未提供结构化简历）",
                jd_pool=format_jd_pool(jd_requirements or {}) or "（无 JD 结构化要求）",
                fundamentals_max=fundamentals_max,
            )
        else:
            prompt = NO_RESUME_PLAN_PROMPT.format(style_brief=style_brief)

        try:
            response = await agent_fast_llm.acomplete(
                prompt,
                response_format={"type": "json_object"},
            )
            return self._parse_plan(str(response.text))
        except Exception as exc:  # noqa: BLE001
            logger.error("Mock interview plan generation failed: %s", exc)
            return self._fallback_plan()

    # ── Question flow ────────────────────────────────────────────────

    def get_current_question(self, session_state: dict, plan: dict) -> dict[str, Any]:
        phases = plan.get("phases", [])
        if not phases:
            return {"done": True, "message": "面试计划为空"}

        current_phase = session_state.get("current_phase", "")
        question_idx = session_state.get("current_question_idx", 0)

        phase = self._find_phase(phases, current_phase)
        if phase is None:
            phase = phases[0]
            current_phase = phase["phase_id"]
            question_idx = 0

        questions = phase.get("questions", [])
        if question_idx >= len(questions):
            next_phase = self._get_next_phase(phases, current_phase)
            if next_phase is None:
                return {"done": True, "message": "面试已完成，感谢参与！"}
            phase = next_phase
            current_phase = phase["phase_id"]
            question_idx = 0
            questions = phase.get("questions", [])

        if not questions:
            return {"done": True, "message": "面试已完成"}

        return {
            "done": False,
            "phase_id": current_phase,
            "phase_name": phase.get("phase_name", current_phase),
            "question_idx": question_idx,
            "total_questions_in_phase": len(questions),
            "question": questions[question_idx].get("question", ""),
        }

    # ── Interviewer response (no scoring) ────────────────────────────

    async def generate_interviewer_response(
        self,
        question: str,
        answer: str,
        phase_id: str,
        *,
        resume_context: str = "",
        qa_history: list[dict] | None = None,
        interviewer_style: str = "professional",
    ) -> dict[str, Any]:
        """Return what the AI interviewer says + whether to follow up."""
        qa_history = qa_history or []
        history_lines: list[str] = []
        for entry in qa_history[-6:]:
            history_lines.append(f"面试官: {entry.get('question', '')}")
            history_lines.append(f"候选人: {entry.get('answer', '')}")

        prompt = INTERVIEWER_RESPONSE_PROMPT.format(
            style_brief=_style_brief(interviewer_style),
            phase_id=phase_id,
            question=question,
            answer=answer,
            resume_context_section=f"简历背景：{resume_context[:500]}" if resume_context else "",
            qa_history_text="\n".join(history_lines) if history_lines else "(首题)",
        )

        try:
            response = await agent_fast_llm.acomplete(
                prompt,
                response_format={"type": "json_object"},
            )
            result = json.loads(str(response.text).strip())
            return {
                "response": str(result.get("response", "好的，下一个问题。")).strip(),
                "action": str(result.get("action", "next_question")).strip(),
                "follow_up_question": str(result.get("follow_up_question", "")).strip(),
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("Interviewer response generation failed: %s", exc)
            return {
                "response": "好的，了解。我们继续下一个问题。",
                "action": "next_question",
                "follow_up_question": "",
            }

    # ── State transitions ────────────────────────────────────────────

    def advance_state(
        self,
        session_state: dict,
        plan: dict,
        interviewer_result: dict,
    ) -> dict:
        phases = plan.get("phases", [])
        current_phase = session_state.get("current_phase", "")
        question_idx = session_state.get("current_question_idx", 0)
        qa_history = list(session_state.get("qa_history", []))

        phase = self._find_phase(phases, current_phase)
        if phase is None and phases:
            phase = phases[0]
            current_phase = phase["phase_id"]
        if phase is None:
            session_state["is_finished"] = True
            return session_state

        questions = phase.get("questions", [])
        action = interviewer_result.get("action", "next_question")

        if action == "follow_up":
            follow_up = interviewer_result.get("follow_up_question", "").strip()
            if follow_up:
                insert_pos = question_idx + 1
                if insert_pos <= len(questions):
                    questions.insert(insert_pos, {"question": follow_up, "is_follow_up": True})

        next_idx = question_idx + 1
        if next_idx >= len(questions):
            next_phase = self._get_next_phase(phases, current_phase)
            if next_phase is None:
                session_state["is_finished"] = True
            else:
                current_phase = next_phase["phase_id"]
                next_idx = 0

        session_state.update({
            "current_phase": current_phase,
            "current_question_idx": next_idx,
            "qa_history": qa_history,
        })
        return session_state

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _find_phase(phases: list[dict], phase_id: str) -> dict | None:
        for phase in phases:
            if phase.get("phase_id") == phase_id:
                return phase
        return None

    @staticmethod
    def _get_next_phase(phases: list[dict], current_phase_id: str) -> dict | None:
        for i, phase in enumerate(phases):
            if phase.get("phase_id") == current_phase_id and i + 1 < len(phases):
                return phases[i + 1]
        return None

    @staticmethod
    def _parse_plan(raw_text: str) -> dict[str, Any]:
        raw_text = raw_text.strip()
        if raw_text.startswith("```"):
            lines = raw_text.splitlines()
            raw_text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        data = json.loads(raw_text)
        if not isinstance(data, dict):
            return {"phases": []}

        if "phases" not in data:
            phase_name_map = {
                "self_intro": "自我介绍",
                "resume_deep_dive": "简历深挖",
                "technical": "技术基础",
                "behavioral": "行为面试",
                "reverse_qa": "反问环节",
            }
            flat_phases: list[dict[str, Any]] = []
            for key, val in data.items():
                if isinstance(val, dict) and "questions" in val:
                    questions = val["questions"]
                    if isinstance(questions, list):
                        flat_phases.append({
                            "phase_id": key,
                            "phase_name": val.get("phase_name", phase_name_map.get(key, key)),
                            "questions": questions,
                        })
                elif isinstance(val, list):
                    flat_phases.append({
                        "phase_id": key,
                        "phase_name": phase_name_map.get(key, key),
                        "questions": val,
                    })
            if flat_phases:
                data = {"phases": flat_phases}
            else:
                return {"phases": []}

        validated_phases: list[dict[str, Any]] = []
        for phase in data["phases"]:
            if not isinstance(phase, dict):
                continue
            phase_id = str(phase.get("phase_id", "")).strip()
            if not phase_id:
                continue
            questions = phase.get("questions", [])
            if not isinstance(questions, list):
                questions = []
            norm_questions: list[dict[str, Any]] = []
            for q in questions:
                if isinstance(q, dict) and q.get("question"):
                    entry: dict[str, Any] = {"question": str(q["question"]).strip()}
                    refs = q.get("grounding_refs")
                    if isinstance(refs, list):
                        entry["grounding_refs"] = [str(r) for r in refs if isinstance(r, (str, int))]
                    norm_questions.append(entry)
                elif isinstance(q, str) and q.strip():
                    norm_questions.append({"question": q.strip()})
            validated_phases.append({
                "phase_id": phase_id,
                "phase_name": str(phase.get("phase_name", phase_id)),
                "questions": norm_questions,
            })
        return {"phases": validated_phases}

    @staticmethod
    def _fallback_plan() -> dict[str, Any]:
        return {
            "phases": [
                {
                    "phase_id": "self_intro",
                    "phase_name": "自我介绍",
                    "questions": [
                        {"question": "请简单介绍一下你自己，包括你的技术背景和求职方向。"}
                    ],
                },
                {
                    "phase_id": "technical",
                    "phase_name": "技术基础",
                    "questions": [
                        {"question": "请解释一下 HTTP 和 HTTPS 的区别。"},
                        {"question": "请描述一下数据库索引的工作原理及其优缺点。"},
                        {"question": "什么是 RESTful API？请举例说明其设计原则。"},
                    ],
                },
                {
                    "phase_id": "behavioral",
                    "phase_name": "行为面试",
                    "questions": [
                        {"question": "请分享一个你在团队中解决技术分歧的经历。"}
                    ],
                },
                {
                    "phase_id": "reverse_qa",
                    "phase_name": "反问环节",
                    "questions": [
                        {"question": "你有什么想问我们的吗？"}
                    ],
                },
            ]
        }


mock_interview_service = MockInterviewService()
