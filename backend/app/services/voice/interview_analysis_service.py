"""Interview transcript analysis — three-stage MapReduce pipeline.

Architecture:
  Stage 0: WhisperX transcription (handled by audio_transcription_service)
  Stage 1: LLM-powered QA extraction with turn index back-referencing
  Stage 2: Per-question deep analysis (Map) with sliding context window
  Stage 3: Global synthesis report (Reduce)

Design principles:
  - Regex parses speaker turns for structure (preserves original text)
  - LLM identifies speaker roles, pairs QA, tags phases & follow-ups
  - LLM outputs turn indices only; text is reconstructed from originals
  - Each question is analyzed with a 3-question sliding context window
  - Resume and JD context are injected into every analysis stage
"""

import asyncio
import json
import logging
import re
from typing import Any

import tiktoken
from llama_index.core import Settings

from app.core.config import settings

logger = logging.getLogger(__name__)

SPEAKER_LINE_RE = re.compile(r"^\s*\*\*\[(?P<speaker>[^\]]+)\]\*\*:\s*(?P<text>.*)$")

try:
    _tokenizer = tiktoken.get_encoding("cl100k_base")
except Exception:
    _tokenizer = None


def _count_tokens(text: str) -> int:
    if not text:
        return 0
    if _tokenizer is None:
        return len(text.encode("utf-8"))
    return len(_tokenizer.encode(text))


def _clean_json_response(raw_text: str) -> dict[str, Any]:
    raw_text = str(raw_text).strip()
    if raw_text.startswith("```json"):
        raw_text = raw_text[7:]
    elif raw_text.startswith("```"):
        raw_text = raw_text[3:]
    if raw_text.endswith("```"):
        raw_text = raw_text[:-3]
    return json.loads(raw_text.strip())


# ══════════════════════════════════════════════════════════════════════════
# Stage 1: LLM-Powered QA Extraction with Turn Index Back-Referencing
# ══════════════════════════════════════════════════════════════════════════


def _parse_speaker_turns(transcript: str) -> list[dict[str, str]]:
    """Parse WhisperX Markdown output into indexed speaker turns.

    Preserves original text verbatim. Returns:
        [{"speaker": "Speaker 1", "text": "原文..."}, ...]
    """
    turns: list[dict[str, str]] = []
    current_speaker: str | None = None
    current_parts: list[str] = []

    for raw_line in transcript.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = SPEAKER_LINE_RE.match(line)
        if match:
            if current_speaker is not None and current_parts:
                turns.append(
                    {
                        "speaker": current_speaker,
                        "text": " ".join(current_parts).strip(),
                    }
                )
            current_speaker = match.group("speaker").strip()
            current_parts = [match.group("text").strip()]
        elif current_speaker is not None:
            current_parts.append(line)

    if current_speaker is not None and current_parts:
        turns.append(
            {
                "speaker": current_speaker,
                "text": " ".join(current_parts).strip(),
            }
        )
    return turns


_LLM_EXTRACTION_PROMPT = """\
你是一名专业的面试对话分析器。下面是一场面试录音的转录文本，已按说话者分段编号。

转录内容：
{turns_text}

你的任务：
1. 判断哪个 Speaker 是面试官（提问方），哪个是候选人（回答方）
2. 将对话组织为结构化的 QA 对

规则：
- 每个 QA 对包含面试官的一个问题和候选人的对应回答
- question_turns: 组成该问题的 turn 编号列表（从 0 开始）
- answer_turns: 组成该回答的 turn 编号列表（从 0 开始）
- question_summary: 用一句话概括面试官这道题问的核心问题（15字以内）
- phase: 面试阶段，可选: self_intro, resume_deep_dive, technical, behavioral, reverse_qa, general
- is_follow_up: 是否为追问
- parent_qa_index: 如果是追问，指向被追问的 QA 编号（从 1 开始）；否则为 null
- 忽略与面试无关的内容（寒暄闲聊、系统提示音、无意义噪音转录）
- 如果面试官连续说了多段（含闲聊/过渡），只把实际提问部分归入 question_turns
- 如果候选人的回答被打断后继续，将所有回答部分合并为同一个 answer_turns

{resume_hint}

输出纯 JSON，不要任何解释：
{{
  "interviewer_speaker": "面试官的 Speaker 标识",
  "candidate_speaker": "候选人的 Speaker 标识",
  "qa_pairs": [
    {{
      "question_turns": [0, 1],
      "answer_turns": [2, 3],
      "question_summary": "简短问题概括",
      "phase": "technical",
      "is_follow_up": false,
      "parent_qa_index": null
    }}
  ]
}}"""


async def extract_qa_pairs_with_llm(
    transcript: str,
    resume_context: str = "",
) -> list[dict[str, Any]]:
    """Stage 1: LLM-powered QA extraction with turn index back-referencing.

    1. Parse turns with regex (preserve original text)
    2. Send turns to LLM for intelligent QA pairing (outputs turn indices only)
    3. Back-reference indices to reconstruct QA pairs from original text

    On LLM failure, falls back to naive alternating-speaker pairing.
    """
    turns = _parse_speaker_turns(transcript)
    if not turns:
        logger.warning("No speaker turns found in transcript.")
        return []

    # Build turns text for LLM (full text, no truncation)
    turns_lines = []
    for i, t in enumerate(turns):
        turns_lines.append(f"[T{i}] {t['speaker']}: {t['text']}")
    turns_text = "\n".join(turns_lines)

    resume_hint = ""
    if resume_context:
        resume_hint = f"候选人简历背景（辅助判断 resume_deep_dive 阶段）：\n{resume_context[:1000]}"

    prompt = _LLM_EXTRACTION_PROMPT.format(
        turns_text=turns_text,
        resume_hint=resume_hint,
    )

    try:
        from app.rag.embeddings import agent_fast_llm

        response = await agent_fast_llm.acomplete(
            prompt,
            response_format={"type": "json_object"},
        )
        result = _clean_json_response(response.text)
        raw_pairs = result.get("qa_pairs", [])

        if not raw_pairs:
            logger.warning("LLM returned empty qa_pairs, falling back.")
            return _fallback_extract(turns)

        # Back-reference: reconstruct QA text from original turns
        qa_pairs: list[dict[str, Any]] = []
        for qi, rp in enumerate(raw_pairs, start=1):
            q_indices = rp.get("question_turns", [])
            a_indices = rp.get("answer_turns", [])

            # Validate indices are within range
            q_indices = [i for i in q_indices if isinstance(i, int) and 0 <= i < len(turns)]
            a_indices = [i for i in a_indices if isinstance(i, int) and 0 <= i < len(turns)]

            if not q_indices or not a_indices:
                continue

            question_text = "\n".join(turns[i]["text"] for i in q_indices)
            answer_text = "\n".join(turns[i]["text"] for i in a_indices)

            if not question_text.strip() or not answer_text.strip():
                continue

            qa_pairs.append({
                "index": qi,
                "question": question_text.strip(),
                "answer": answer_text.strip(),
                "question_summary": str(rp.get("question_summary", "")).strip(),
                "phase": str(rp.get("phase", "general")).strip(),
                "is_follow_up": bool(rp.get("is_follow_up", False)),
                "parent_index": rp.get("parent_qa_index"),
            })

        # Re-number indices sequentially
        for i, pair in enumerate(qa_pairs, start=1):
            pair["index"] = i

        logger.info(
            "Stage 1 complete: LLM extracted %d QA pairs from %d turns "
            "(interviewer=%s, candidate=%s).",
            len(qa_pairs),
            len(turns),
            result.get("interviewer_speaker", "?"),
            result.get("candidate_speaker", "?"),
        )
        return qa_pairs

    except Exception as exc:
        logger.warning("LLM QA extraction failed (%s), falling back to naive pairing.", exc)
        return _fallback_extract(turns)


def _fallback_extract(turns: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Fallback: naive alternating-speaker QA pairing when LLM fails."""
    if len(turns) < 2:
        return []

    # Guess: first speaker is interviewer
    interviewer = turns[0]["speaker"]
    qa_pairs: list[dict[str, Any]] = []
    i = 0
    qi = 1

    while i < len(turns):
        question_parts: list[str] = []
        answer_parts: list[str] = []

        while i < len(turns) and turns[i]["speaker"] == interviewer:
            question_parts.append(turns[i]["text"])
            i += 1
        while i < len(turns) and turns[i]["speaker"] != interviewer:
            answer_parts.append(turns[i]["text"])
            i += 1

        question = "\n".join(p for p in question_parts if p).strip()
        answer = "\n".join(p for p in answer_parts if p).strip()
        if question and answer:
            qa_pairs.append({
                "index": qi,
                "question": question,
                "answer": answer,
                "question_summary": "",
                "phase": "general",
                "is_follow_up": False,
                "parent_index": None,
            })
            qi += 1

    return qa_pairs


# ══════════════════════════════════════════════════════════════════════════
# Stage 2: Per-Question Deep Analysis (Map) with Sliding Context Window
# ══════════════════════════════════════════════════════════════════════════

_SLIDING_WINDOW_SIZE = 3  # include up to 3 preceding QA pairs

_PER_QUESTION_PROMPT = """\
你是一名资深且严格的技术面试官。请对下面这道面试题的候选人回答进行深度分析。

{resume_section}
{jd_section}
{context_section}

【当前题目（第 {index} 题，共 {total} 题）】
面试官问题：
{question}

候选人回答：
{answer}

请输出纯 JSON（不要 markdown 代码块，不要解释文字）：
{{
  "score": 0到10的评分,
  "critique": "不足之处的详细点评（指出技术缺陷、遗漏点、错误点，200字以内）",
  "improved_answer": "更完整、更严谨的参考答案",
  "tags": ["知识点标签1", "标签2"]
}}"""


def _build_sliding_context(
    qa_pairs: list[dict[str, Any]],
    current_index: int,
) -> str:
    """Build sliding window context for the current question.

    Includes:
    1. Follow-up chain parent (even if outside window)
    2. Up to SLIDING_WINDOW_SIZE preceding QA pairs
    """
    current = qa_pairs[current_index]
    context_parts: list[str] = []

    # Include follow-up chain parent if outside the sliding window
    parent_idx = current.get("parent_index")
    window_start = max(0, current_index - _SLIDING_WINDOW_SIZE)

    if parent_idx is not None and isinstance(parent_idx, int):
        parent_pos = parent_idx - 1  # convert 1-based index to 0-based
        if 0 <= parent_pos < len(qa_pairs) and parent_pos < window_start:
            p = qa_pairs[parent_pos]
            context_parts.append(
                f"[追问源头 — 第{p['index']}题]\n"
                f"问: {p['question'][:300]}\n"
                f"答: {p['answer'][:300]}"
            )

    # Sliding window: preceding questions
    for i in range(window_start, current_index):
        p = qa_pairs[i]
        context_parts.append(
            f"[第{p['index']}题]\n"
            f"问: {p['question'][:300]}\n"
            f"答: {p['answer'][:300]}"
        )

    if not context_parts:
        return ""

    return "前文上下文：\n" + "\n\n".join(context_parts)


async def _analyze_single_question(
    qa_pair: dict[str, Any],
    context_text: str,
    total_questions: int,
    resume_context: str = "",
    jd_context: str = "",
) -> dict[str, Any]:
    """Analyze a single QA pair and return structured result."""
    resume_section = ""
    if resume_context:
        resume_section = f"候选人简历背景：\n{resume_context[:1000]}"

    jd_section = ""
    if jd_context:
        jd_section = f"目标岗位 JD：\n{jd_context[:500]}"

    prompt = _PER_QUESTION_PROMPT.format(
        resume_section=resume_section,
        jd_section=jd_section,
        context_section=context_text,
        index=qa_pair["index"],
        total=total_questions,
        question=qa_pair["question"],
        answer=qa_pair["answer"],
    )

    try:
        response = await Settings.llm.acomplete(prompt)
        result = _clean_json_response(response.text)

        return {
            "index": qa_pair["index"],
            "phase": qa_pair.get("phase", "general"),
            "question": qa_pair["question"],
            "answer": qa_pair["answer"],
            "score": float(result.get("score", 0) or 0),
            "critique": str(result.get("critique", "")).strip(),
            "improved_answer": str(result.get("improved_answer", "")).strip(),
            "tags": result.get("tags", []),
        }
    except Exception as exc:
        logger.error("Per-question analysis failed for Q%d: %s", qa_pair["index"], exc)
        return {
            "index": qa_pair["index"],
            "phase": qa_pair.get("phase", "general"),
            "question": qa_pair["question"],
            "answer": qa_pair["answer"],
            "score": 0,
            "critique": "分析失败",
            "improved_answer": "",
            "tags": [],
        }


# ══════════════════════════════════════════════════════════════════════════
# Stage 3: Global Synthesis Report (Reduce)
# ══════════════════════════════════════════════════════════════════════════

_SYNTHESIS_PROMPT = """\
你是一名资深技术面试官。下面是一场完整面试的逐题分析结果。
请基于这些结果，输出全局综合评估报告。

{resume_section}
{jd_section}

逐题分析摘要：
{per_question_summary}

请输出纯 JSON（不要 markdown，不要解释）：
{{
  "interview_metadata": {{
    "total_questions": 题目总数,
    "phases": ["检测到的面试阶段列表"]
  }},
  "overall": {{
    "score": 0到10的综合评分,
    "grade": "字母等级如 A/B+/C",
    "verdict": "建议通过/待定/不建议通过",
    "feedback": "500字以内的整体评价",
    "strengths": ["优点1", "优点2"],
    "weaknesses": ["不足1", "不足2"],
    "improvement_plan": ["改进建议1", "改进建议2"]
  }},
  "phase_summary": [
    {{
      "phase": "阶段ID",
      "phase_name": "阶段中文名",
      "score": 该阶段平均分,
      "question_count": 该阶段题目数,
      "summary": "该阶段表现总结"
    }}
  ],
  "skill_radar": {{
    "系统设计": 0-10, "编码能力": 0-10,
    "基础知识": 0-10, "沟通表达": 0-10, "项目经验": 0-10
  }}
}}"""

_PHASE_NAME_MAP: dict[str, str] = {
    "self_intro": "自我介绍",
    "resume_deep_dive": "简历项目深挖",
    "technical": "技术基础",
    "behavioral": "行为面试",
    "reverse_qa": "反问环节",
    "general": "综合",
}


async def _synthesize_report(
    per_question_results: list[dict[str, Any]],
    resume_context: str = "",
    jd_context: str = "",
) -> dict[str, Any]:
    """Stage 3: Synthesize per-question results into a global report."""

    # Build per-question summary for the synthesis prompt
    summary_lines: list[str] = []
    for pq in per_question_results:
        summary_lines.append(
            f"第{pq['index']}题 [{_PHASE_NAME_MAP.get(pq.get('phase', ''), pq.get('phase', ''))}] "
            f"评分:{pq['score']}/10\n"
            f"  问题: {pq['question'][:80]}...\n"
            f"  不足: {pq['critique'][:100]}...\n"
            f"  标签: {', '.join(pq.get('tags', []))}"
        )

    resume_section = ""
    if resume_context:
        resume_section = f"候选人简历背景：\n{resume_context[:800]}"

    jd_section = ""
    if jd_context:
        jd_section = f"目标岗位 JD：\n{jd_context[:500]}"

    prompt = _SYNTHESIS_PROMPT.format(
        resume_section=resume_section,
        jd_section=jd_section,
        per_question_summary="\n\n".join(summary_lines),
    )

    try:
        response = await Settings.llm.acomplete(prompt)
        synthesis = _clean_json_response(response.text)

        # Build the final report
        return {
            "interview_metadata": synthesis.get("interview_metadata", {
                "total_questions": len(per_question_results),
                "phases": list({pq.get("phase", "general") for pq in per_question_results}),
            }),
            "overall": {
                "score": float(synthesis.get("overall", {}).get("score", 0) or 0),
                "grade": str(synthesis.get("overall", {}).get("grade", "")),
                "verdict": str(synthesis.get("overall", {}).get("verdict", "")),
                "feedback": str(synthesis.get("overall", {}).get("feedback", "")),
                "strengths": synthesis.get("overall", {}).get("strengths", []),
                "weaknesses": synthesis.get("overall", {}).get("weaknesses", []),
                "improvement_plan": synthesis.get("overall", {}).get("improvement_plan", []),
            },
            "phase_summary": synthesis.get("phase_summary", []),
            "per_question": per_question_results,
            "skill_radar": synthesis.get("skill_radar", {}),
        }
    except Exception as exc:
        logger.error("Report synthesis failed: %s", exc)
        # Fallback: compute basic stats from per-question results
        scores = [pq["score"] for pq in per_question_results if pq["score"] > 0]
        avg_score = sum(scores) / len(scores) if scores else 0.0
        return {
            "interview_metadata": {
                "total_questions": len(per_question_results),
                "phases": list({pq.get("phase", "general") for pq in per_question_results}),
            },
            "overall": {
                "score": round(avg_score, 1),
                "grade": "",
                "verdict": "",
                "feedback": "综合报告生成失败，仅提供逐题分析结果。",
                "strengths": [],
                "weaknesses": [],
                "improvement_plan": [],
            },
            "phase_summary": [],
            "per_question": per_question_results,
            "skill_radar": {},
        }


# ══════════════════════════════════════════════════════════════════════════
# Public Entry Point
# ══════════════════════════════════════════════════════════════════════════


async def analyze_interview(
    transcript: str,
    *,
    resume_context: str = "",
    jd_context: str = "",
) -> dict[str, Any]:
    """Analyze an interview transcript using the three-stage MapReduce pipeline.

    Args:
        transcript: WhisperX diarized transcript (Markdown format)
        resume_context: Plain text resume content (recommended)
        jd_context: Plain text job description (optional)

    Returns:
        Complete analysis report dict matching the v2 report schema.
    """
    try:
        # ── Stage 1: LLM-powered QA extraction ──────────────────────
        qa_pairs = await extract_qa_pairs_with_llm(transcript, resume_context)

        if not qa_pairs:
            logger.warning("No QA pairs extracted; returning empty report.")
            return {
                "interview_metadata": {"total_questions": 0, "phases": []},
                "overall": {
                    "score": 0, "grade": "", "verdict": "",
                    "feedback": "无法从转录文本中识别出有效的问答对。",
                    "strengths": [], "weaknesses": [], "improvement_plan": [],
                },
                "phase_summary": [],
                "per_question": [],
                "skill_radar": {},
            }

        logger.info(
            "Stage 1 complete: extracted %d QA pairs (%d tokens in transcript).",
            len(qa_pairs),
            _count_tokens(transcript),
        )

        # ── Stage 2: Per-question analysis (Map, concurrent) ─────────
        tasks: list[asyncio.Task] = []
        for idx, pair in enumerate(qa_pairs):
            context_text = _build_sliding_context(qa_pairs, idx)
            task = asyncio.create_task(
                _analyze_single_question(
                    qa_pair=pair,
                    context_text=context_text,
                    total_questions=len(qa_pairs),
                    resume_context=resume_context,
                    jd_context=jd_context,
                )
            )
            tasks.append(task)

        per_question_results = await asyncio.gather(*tasks)
        per_question_results = list(per_question_results)

        logger.info("Stage 2 complete: analyzed %d questions.", len(per_question_results))

        # ── Stage 3: Global synthesis (Reduce) ───────────────────────
        report = await _synthesize_report(
            per_question_results,
            resume_context=resume_context,
            jd_context=jd_context,
        )

        logger.info(
            "Stage 3 complete: overall score %.1f, grade %s.",
            report.get("overall", {}).get("score", 0),
            report.get("overall", {}).get("grade", "N/A"),
        )

        return report

    except Exception as e:
        logger.error(f"Analysis pipeline failed: {e}")
        raise


__all__ = ["analyze_interview", "extract_qa_pairs_with_llm"]
