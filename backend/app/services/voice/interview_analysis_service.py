"""Interview transcript analysis — three-stage MapReduce pipeline.

Architecture:
  Stage 0: WhisperX transcription (handled by audio_transcription_service)
  Stage 1: Full LLM QA extraction (role identification, pairing, tagging)
  Stage 2: Per-question deep analysis (Map) with sliding context window
  Stage 3: Global synthesis report (Reduce)

Design principles:
  - LLM reads raw transcript and extracts QA pairs directly
  - Handles speaker diarization failures, mixed turns, short/long exchanges
  - Long transcripts are chunked with overlap and deduplicated
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
# Stage 1: Full LLM QA Extraction
# ══════════════════════════════════════════════════════════════════════════

# Maximum tokens to send in a single LLM extraction call.
# DeepSeek V4 Flash supports 1M context; we stay well within limits.
_EXTRACTION_MAX_TOKENS = 120_000

_LLM_EXTRACTION_PROMPT = """\
你是一名专业的面试对话分析专家。下面是一场面试录音的语音转录文本（ASR 输出，可能有错别字和口语化表达）。

转录文本：
---
{transcript}
---

{resume_hint}

你的任务：仔细阅读整段对话，从中提取面试官与候选人之间的所有问答交互（QA pairs）。

提取规则：
1. **角色识别**：根据对话内容判断谁是面试官（提问方）、谁是候选人（回答方）。面试官通常会提出问题、追问细节、引导话题；候选人会介绍自己、回答问题。
2. **完整保留**：question 和 answer 必须高保真还原转录原文，包括口语化表达、语气词、非技术性闲聊。不要简化、不要省略、不要改写语义。用户需要看到完整的面试过程。
3. **问题提取**：提取面试官的每一个独立问题或话题。面试官说的所有内容（包括评论、过渡、闲聊）都应完整保留在 question 字段中。
4. **回答提取**：提取候选人针对该话题的完整回答。如果候选人的回答被面试官打断后继续，应合并为完整回答。
5. **追问识别**：如果面试官针对候选人的某个回答继续追问，标记为追问并关联到原始问题。
6. **仅去除 ASR 乱码**：只去除明显的 ASR 错误产物（如无意义的外语碎片、乱码符号），保留所有有意义的中文内容。
7. **问题概括**：question_summary 用一句简短的话概括这道题/话题的核心内容（15字以内）。

输出纯 JSON，不要任何解释文字：
{{
  "qa_pairs": [
    {{
      "question": "面试官说的完整原文",
      "answer": "候选人说的完整原文",
      "question_summary": "简短概括",
      "phase": "self_intro 或 resume_deep_dive 或 technical 或 behavioral 或 reverse_qa 或 general",
      "is_follow_up": false,
      "parent_qa_index": null
    }}
  ]
}}

注意：parent_qa_index 从 1 开始计数，指向本次输出中被追问的 QA 编号。"""


async def extract_qa_pairs_with_llm(
    transcript: str,
    resume_context: str = "",
) -> list[dict[str, Any]]:
    """Stage 1: Full LLM-powered QA extraction.

    Sends the raw transcript to LLM and lets it identify speaker roles,
    extract QA pairs, tag phases, and detect follow-up chains.

    For very long transcripts, splits into overlapping chunks and merges.
    """
    if not transcript or not transcript.strip():
        logger.warning("Empty transcript provided.")
        return []

    token_count = _count_tokens(transcript)
    logger.info("Stage 1: transcript has %d tokens.", token_count)

    if token_count <= _EXTRACTION_MAX_TOKENS:
        return await _extract_single_pass(transcript, resume_context)

    # Chunked extraction for very long transcripts
    return await _extract_chunked(transcript, resume_context, token_count)


async def _extract_single_pass(
    transcript: str,
    resume_context: str = "",
) -> list[dict[str, Any]]:
    """Extract QA pairs in a single LLM call."""
    resume_hint = ""
    if resume_context:
        resume_hint = f"候选人简历背景（辅助判断阶段和评估）：\n{resume_context[:1500]}"

    prompt = _LLM_EXTRACTION_PROMPT.format(
        transcript=transcript,
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
            logger.warning("LLM returned empty qa_pairs.")
            return []

        qa_pairs = _normalize_qa_pairs(raw_pairs)
        logger.info("Stage 1 complete: extracted %d QA pairs.", len(qa_pairs))
        return qa_pairs

    except Exception as exc:
        logger.error("LLM QA extraction failed: %s", exc)
        return []


async def _extract_chunked(
    transcript: str,
    resume_context: str,
    total_tokens: int,
) -> list[dict[str, Any]]:
    """Extract QA pairs from a long transcript by splitting into chunks.

    Uses sentence-level splitting with overlap to avoid cutting mid-question.
    """
    # Split by sentences (Chinese periods, question marks, or newlines)
    sentences = re.split(r'(?<=[。？！\n])', transcript)
    sentences = [s for s in sentences if s.strip()]

    chunks: list[str] = []
    current_chunk: list[str] = []
    current_tokens = 0
    chunk_limit = _EXTRACTION_MAX_TOKENS - 5000  # reserve space for prompt

    for sent in sentences:
        sent_tokens = _count_tokens(sent)
        if current_tokens + sent_tokens > chunk_limit and current_chunk:
            chunks.append("".join(current_chunk))
            # Keep last ~20% of sentences as overlap
            overlap_count = max(1, len(current_chunk) // 5)
            current_chunk = current_chunk[-overlap_count:]
            current_tokens = sum(_count_tokens(s) for s in current_chunk)
        current_chunk.append(sent)
        current_tokens += sent_tokens

    if current_chunk:
        chunks.append("".join(current_chunk))

    logger.info(
        "Stage 1: splitting %d-token transcript into %d chunks.",
        total_tokens, len(chunks),
    )

    # Extract from each chunk
    all_pairs: list[dict[str, Any]] = []
    for ci, chunk in enumerate(chunks):
        chunk_pairs = await _extract_single_pass(chunk, resume_context)
        logger.info("Stage 1 chunk %d/%d: extracted %d pairs.", ci + 1, len(chunks), len(chunk_pairs))
        all_pairs.extend(chunk_pairs)

    # Deduplicate overlapping QA pairs (by question_summary similarity)
    deduped = _deduplicate_qa_pairs(all_pairs)

    # Re-number
    for i, pair in enumerate(deduped, start=1):
        pair["index"] = i

    logger.info("Stage 1 complete: %d QA pairs after dedup (from %d raw).", len(deduped), len(all_pairs))
    return deduped


def _normalize_qa_pairs(raw_pairs: list[dict]) -> list[dict[str, Any]]:
    """Normalize and validate raw QA pairs from LLM output."""
    qa_pairs: list[dict[str, Any]] = []

    for qi, rp in enumerate(raw_pairs, start=1):
        question = str(rp.get("question", "")).strip()
        answer = str(rp.get("answer", "")).strip()

        if not question or not answer:
            continue

        # Skip very short pairs that are likely noise
        if len(question) < 5 and len(answer) < 5:
            continue

        qa_pairs.append({
            "index": qi,
            "question": question,
            "answer": answer,
            "question_summary": str(rp.get("question_summary", "")).strip(),
            "phase": str(rp.get("phase", "general")).strip(),
            "is_follow_up": bool(rp.get("is_follow_up", False)),
            "parent_index": rp.get("parent_qa_index"),
        })

    # Re-number sequentially
    for i, pair in enumerate(qa_pairs, start=1):
        pair["index"] = i

    return qa_pairs


def _deduplicate_qa_pairs(pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove duplicate QA pairs from chunked extraction.

    Uses question text overlap ratio to detect duplicates.
    """
    if not pairs:
        return []

    deduped: list[dict[str, Any]] = [pairs[0]]

    for pair in pairs[1:]:
        is_dup = False
        q = pair["question"]
        for existing in deduped[-3:]:  # Only check last 3 to avoid O(n^2)
            eq = existing["question"]
            # Check character overlap
            shorter = min(len(q), len(eq))
            if shorter == 0:
                continue
            # Simple: check if one is a substring of the other
            if q in eq or eq in q:
                is_dup = True
                break
            # Check prefix overlap (common when chunks split mid-question)
            overlap = 0
            for c1, c2 in zip(q, eq):
                if c1 == c2:
                    overlap += 1
                else:
                    break
            if overlap > shorter * 0.6:
                is_dup = True
                break
        if not is_dup:
            deduped.append(pair)

    return deduped


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
