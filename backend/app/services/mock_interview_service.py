"""Mock interview orchestration service.

Lifecycle:
  1. generate_plan()                  — LLM reads resume → phased interview plan
  2. get_current_question()           — returns the current question
  3. generate_interviewer_response()  — AI interviewer reacts naturally (no scoring)
  4. advance_state()                  — advance to next question or follow-up
  5. batch_evaluate()                 — after interview ends, score all Q&A at once

Interview phases (configurable via plan):
  - self_intro       — 自我介绍
  - resume_deep_dive — 简历项目深挖
  - technical        — 八股/算法
  - behavioral       — 行为面试 (STAR)
  - reverse_qa       — 反问面试官

Design: During the interview, the AI acts as a real interviewer — it asks
questions and responds naturally without showing scores or feedback. All
scoring happens in batch_evaluate() after the interview ends.
"""

import json
import logging
from typing import Any

from app.rag.embeddings import agent_fast_llm

logger = logging.getLogger(__name__)


# ── Plan generation ──────────────────────────────────────────────────────

PLAN_PROMPT = """你是一名资深技术面试官。根据下面的简历信息，生成一份结构化面试计划。

要求：
1. 包含以下阶段（按顺序）：
   - self_intro: 自我介绍（1个问题）
   - resume_deep_dive: 针对简历中的项目经历进行深挖（2-4个问题，根据简历内容）
   - technical: 与简历技术栈相关的八股/基础知识（2-3个问题）
   - behavioral: 行为面试题（1-2个问题，用STAR法则引导）
   - reverse_qa: 反问环节（1个引导语）

2. 每个问题要具体、有针对性，不要空泛。
3. resume_deep_dive 的问题要紧密围绕简历内容。
4. technical 的问题要与简历中提到的技术栈相关。

输出纯 JSON：
{{
  "phases": [
    {{
      "phase_id": "self_intro",
      "phase_name": "自我介绍",
      "questions": [
        {{"question": "请用2分钟简单介绍一下你自己，包括你的技术背景和求职方向。"}}
      ]
    }},
    ...
  ]
}}

简历信息：
{resume_context}
"""

NO_RESUME_PLAN_PROMPT = """你是一名资深技术面试官。候选人没有提供简历，请生成一份通用技术面试计划。

包含阶段：self_intro(1题), technical(3题, 通用后端/前端基础), behavioral(1题), reverse_qa(1题)。

输出纯 JSON，结构同上。"""


# ── Interviewer response prompt ──────────────────────────────────────────

INTERVIEWER_RESPONSE_PROMPT = """你是一名正在面试的资深技术面试官。请根据候选人的回答，给出面试官的自然回应。

当前阶段：{phase_id}
当前问题：{question}
候选人回答：{answer}
{resume_context_section}
之前的对话：
{qa_history_text}

规则：
- 像真正的面试官一样自然回应，不要给出评分或反馈
- 根据回答质量决定下一步：
  - 如果回答不够深入或有疑点，追问细节（action: "follow_up"）
  - 如果回答充分，自然过渡到下一个问题（action: "next_question"）
  - 如果当前阶段所有问题已问完，结束阶段（action: "next_question"）
- 回应要简短自然（1-3句话），像真实对话
- 过渡语要自然，比如"嗯，了解。那我接着想问一下..."

输出 JSON：
{{
  "response": "面试官的自然回应文本",
  "action": "follow_up" 或 "next_question",
  "follow_up_question": "追问的问题（仅当 action 为 follow_up 时填写，否则为空）"
}}"""

# ── Batch evaluation prompt ──────────────────────────────────────────────

BATCH_EVALUATE_PROMPT = """你是一名资深面试官，面试刚刚结束。请对整场面试进行全面评估。

面试问答记录：
{qa_records}

{resume_context_section}

请输出 JSON：
{{
  "overall_score": 0-10的综合评分,
  "overall_feedback": "300字以内的整体评价",
  "strengths": ["优点1", "优点2"],
  "weaknesses": ["不足1", "不足2"],
  "improvement_suggestions": ["建议1", "建议2"],
  "per_question": [
    {{
      "question": "问题原文",
      "answer_summary": "回答要点概括",
      "score": 0-10,
      "feedback": "针对这道题的简短评价"
    }}
  ]
}}"""


class MockInterviewService:
    """Orchestrates a mock interview session."""

    # ── Plan Generation ───────────────────────────────────────────────

    async def generate_plan(self, resume_context: str = "") -> dict[str, Any]:
        """Generate a structured interview plan from resume context."""
        if resume_context.strip():
            prompt = PLAN_PROMPT.format(resume_context=resume_context)
        else:
            prompt = NO_RESUME_PLAN_PROMPT

        try:
            response = await agent_fast_llm.acomplete(
                prompt,
                response_format={"type": "json_object"},
            )
            return self._parse_plan(str(response.text))
        except Exception as exc:  # noqa: BLE001
            logger.error("Mock interview plan generation failed: %s", exc)
            return self._fallback_plan()

    # ── Question Flow ─────────────────────────────────────────────────

    def get_current_question(self, session_state: dict, plan: dict) -> dict[str, Any]:
        """Return the current question based on session state."""
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

    # ── Interviewer Response (no scoring) ─────────────────────────────

    async def generate_interviewer_response(
        self,
        question: str,
        answer: str,
        phase_id: str,
        resume_context: str = "",
        qa_history: list[dict] | None = None,
    ) -> dict[str, Any]:
        """Generate the interviewer's natural response (no scoring).

        Returns:
            - response: what the interviewer says
            - action: "follow_up" or "next_question"
            - follow_up_question: the follow-up question (if action is follow_up)
        """
        qa_history = qa_history or []
        history_lines = []
        for entry in qa_history[-6:]:  # last 6 Q&A for context
            history_lines.append(f"面试官: {entry.get('question', '')}")
            history_lines.append(f"候选人: {entry.get('answer', '')}")

        prompt = INTERVIEWER_RESPONSE_PROMPT.format(
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

    # ── State Transitions ─────────────────────────────────────────────

    def advance_state(
        self,
        session_state: dict,
        plan: dict,
        interviewer_result: dict,
    ) -> dict:
        """Advance session state after an answer.

        Returns the updated session state dict (not persisted — caller must save).
        """
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

        # Handle follow-up: insert into current phase's questions
        if action == "follow_up":
            follow_up = interviewer_result.get("follow_up_question", "").strip()
            if follow_up:
                insert_pos = question_idx + 1
                if insert_pos <= len(questions):
                    questions.insert(insert_pos, {"question": follow_up, "is_follow_up": True})

        # Advance to next question
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

    # ── Batch Evaluation (after interview ends) ───────────────────────

    async def batch_evaluate(
        self,
        qa_history: list[dict],
        resume_context: str = "",
    ) -> dict[str, Any]:
        """Evaluate all Q&A pairs at once after the interview ends.

        Returns analysis_json compatible format with per-question scores.
        """
        if not qa_history:
            return {
                "overall_score": 0,
                "overall_feedback": "没有回答记录",
                "per_question": [],
            }

        qa_lines = []
        for i, entry in enumerate(qa_history, 1):
            qa_lines.append(
                f"第{i}题:\n"
                f"  问题: {entry.get('question', '')}\n"
                f"  回答: {entry.get('answer', '')}"
            )

        prompt = BATCH_EVALUATE_PROMPT.format(
            qa_records="\n\n".join(qa_lines),
            resume_context_section=f"简历背景：{resume_context[:500]}" if resume_context else "",
        )

        try:
            response = await agent_fast_llm.acomplete(
                prompt,
                response_format={"type": "json_object"},
            )
            result = json.loads(str(response.text).strip())
            return {
                "overall_score": float(result.get("overall_score", 0)),
                "overall_feedback": str(result.get("overall_feedback", "")),
                "strengths": result.get("strengths", []),
                "weaknesses": result.get("weaknesses", []),
                "improvement_suggestions": result.get("improvement_suggestions", []),
                "per_question": result.get("per_question", []),
                "qa_history": qa_history,
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("Batch evaluation failed: %s", exc)
            return {
                "overall_score": 0,
                "overall_feedback": "评估失败",
                "per_question": [],
                "qa_history": qa_history,
            }

    # ── Helpers ───────────────────────────────────────────────────────

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

        # Handle flat format: {"self_intro": {"questions": [...]}, ...}
        # Convert to canonical: {"phases": [{"phase_id": "self_intro", ...}]}
        if "phases" not in data:
            phase_name_map = {
                "self_intro": "自我介绍",
                "resume_deep_dive": "简历深挖",
                "technical": "技术基础",
                "behavioral": "行为面试",
                "reverse_qa": "反问环节",
            }
            flat_phases = []
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
                    # Direct list: {"self_intro": ["问题1", "问题2"]}
                    flat_phases.append({
                        "phase_id": key,
                        "phase_name": phase_name_map.get(key, key),
                        "questions": val,
                    })
            if flat_phases:
                data = {"phases": flat_phases}
            else:
                return {"phases": []}

        validated_phases = []
        for phase in data["phases"]:
            if not isinstance(phase, dict):
                continue
            phase_id = str(phase.get("phase_id", "")).strip()
            if not phase_id:
                continue
            questions = phase.get("questions", [])
            if not isinstance(questions, list):
                questions = []
            # Normalize questions: accept both {"question": "..."} and plain strings
            norm_questions = []
            for q in questions:
                if isinstance(q, dict) and q.get("question"):
                    norm_questions.append({"question": str(q["question"]).strip()})
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
