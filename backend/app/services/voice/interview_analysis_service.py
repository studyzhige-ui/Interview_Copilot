"""Interview transcript analysis — three-stage MapReduce pipeline.

Architecture:
  Stage 0: WhisperX transcription (handled by audio_transcription_service)
  Stage 1: Deterministic QA extraction + LLM metadata annotation
  Stage 2: Per-question deep analysis (Map) with sliding context window
  Stage 3: Global synthesis report (Reduce)

Design principles:
  - QA text is extracted deterministically (zero fidelity loss)
  - LLM only annotates metadata (phase tags, follow-up chains)
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
# Stage 1a: Deterministic QA Extraction (zero fidelity loss)
# ══════════════════════════════════════════════════════════════════════════


def _parse_speaker_turns(transcript: str) -> list[dict[str, str]]:
    """Parse WhisperX Markdown output into speaker turns."""
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


def _build_qa_pairs(turns: list[dict[str, str]]) -> list[dict[str, str]]:
    """Pair consecutive interviewer/candidate turns into QA pairs."""
    if len(turns) < 2:
        return []

    interviewer = turns[0]["speaker"]
    qa_pairs: list[dict[str, str]] = []
    i = 0

    while i < len(turns):
        question_parts: list[str] = []
        answer_parts: list[str] = []

        while i < len(turns) and turns[i]["speaker"] == interviewer:
            question_parts.append(turns[i]["text"])
            i += 1

        while i < len(turns) and turns[i]["speaker"] != interviewer:
            answer_parts.append(turns[i]["text"])
            i += 1

        question = "\n".join(part for part in question_parts if part).strip()
        answer = "\n".join(part for part in answer_parts if part).strip()
        if question and answer:
            qa_pairs.append({"question": question, "answer": answer})

    return qa_pairs


def _fallback_pairs_from_paragraphs(transcript: str) -> list[dict[str, str]]:
    """Fallback: split by double newlines, alternate as Q&A."""
    parts = [part.strip() for part in transcript.split("\n\n") if part.strip()]
    qa_pairs: list[dict[str, str]] = []
    for idx in range(0, len(parts) - 1, 2):
        qa_pairs.append({"question": parts[idx], "answer": parts[idx + 1]})
    return qa_pairs


def extract_qa_pairs(transcript: str) -> list[dict[str, Any]]:
    """Stage 1a: Deterministic QA extraction from transcript.

    Returns indexed QA pairs with original text preserved verbatim.
    """
    turns = _parse_speaker_turns(transcript)
    qa_pairs = _build_qa_pairs(turns)
    if not qa_pairs:
        qa_pairs = _fallback_pairs_from_paragraphs(transcript)

    return [
        {"index": i + 1, "question": pair["question"], "answer": pair["answer"]}
        for i, pair in enumerate(qa_pairs)
    ]


# ══════════════════════════════════════════════════════════════════════════
# Stage 1b: LLM Metadata Annotation (only tags, never modifies text)
# ══════════════════════════════════════════════════════════════════════════

_ANNOTATION_PROMPT = """\
你是一名资深面试官助手。下面是一场面试中提取的问题列表（仅问题，不含回答）。
请为每个问题标注：
1. phase: 面试阶段，可选值: self_intro, resume_deep_dive, technical, behavioral, reverse_qa, general
2. is_follow_up: 是否为追问（即面试官针对前一个问题的回答继续追问）
3. parent_index: 如果是追问，指向被追问的原始问题编号；否则为 null

{resume_hint}

问题列表：
{questions_json}

输出纯 JSON，不要输出解释：
{{
  "annotations": [
    {{"index": 1, "phase": "...", "is_follow_up": false, "parent_index": null}},
    ...
  ]
}}"""


async def _annotate_qa_metadata(
    qa_pairs: list[dict[str, Any]],
    resume_context: str = "",
) -> list[dict[str, Any]]:
    """Stage 1b: Use LLM to annotate phase and follow-up metadata.

    On failure, gracefully degrades to all-general with no follow-up chains.
    Original QA text is NEVER modified.
    """
    questions_for_llm = [
        {"index": p["index"], "question": p["question"][:200]}
        for p in qa_pairs
    ]

    resume_hint = ""
    if resume_context:
        resume_hint = f"简历摘要（用于判断 resume_deep_dive 阶段）：\n{resume_context[:800]}"

    prompt = _ANNOTATION_PROMPT.format(
        resume_hint=resume_hint,
        questions_json=json.dumps(questions_for_llm, ensure_ascii=False),
    )

    try:
        from app.rag.embeddings import agent_fast_llm

        response = await agent_fast_llm.acomplete(
            prompt,
            response_format={"type": "json_object"},
        )
        result = _clean_json_response(response.text)
        annotations = result.get("annotations", [])

        # Build lookup: index -> annotation
        anno_map: dict[int, dict] = {}
        for a in annotations:
            idx = a.get("index")
            if isinstance(idx, int):
                anno_map[idx] = a

        # Merge annotations into QA pairs (never touch question/answer text)
        for pair in qa_pairs:
            anno = anno_map.get(pair["index"], {})
            pair["phase"] = str(anno.get("phase", "general")).strip()
            pair["is_follow_up"] = bool(anno.get("is_follow_up", False))
            pair["parent_index"] = anno.get("parent_index")

        logger.info("QA metadata annotation completed for %d pairs.", len(qa_pairs))
        return qa_pairs

    except Exception as exc:
        logger.warning(
            "LLM metadata annotation failed, degrading gracefully: %s", exc
        )
        for pair in qa_pairs:
            pair["phase"] = "general"
            pair["is_follow_up"] = False
            pair["parent_index"] = None
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
        # ── Stage 1a: Deterministic QA extraction ────────────────────
        qa_pairs = extract_qa_pairs(transcript)

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
            "Stage 1a complete: extracted %d QA pairs from transcript (%d tokens).",
            len(qa_pairs),
            _count_tokens(transcript),
        )

        # ── Stage 1b: LLM metadata annotation ───────────────────────
        qa_pairs = await _annotate_qa_metadata(qa_pairs, resume_context)

        logger.info("Stage 1b complete: metadata annotated for %d pairs.", len(qa_pairs))

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


__all__ = ["analyze_interview", "extract_qa_pairs"]
