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
你是一位经验丰富的技术教练，正在帮助下面这位候选人复盘他刚结束的一场模拟面试。
**这不是把关人，而是成长陪练**：你的目标是用最高信号量的方式告诉他下一步该练什么。
不要给"建议通过 / 不建议通过"这种判决；不要打字母等级。

═════════ 候选人简历（全文） ═════════
{resume_context}

═════════ 目标岗位 JD（全文） ═════════
{jd_context}

═════════ 逐题分析摘要 ═════════
{per_question_summary}

═════════ 你的任务 ═════════

输出一份成长导向的综合复盘。请严格按下面 JSON schema 输出（不要 markdown 代码块、不要前后说明）：

{{
  "interview_metadata": {{
    "total_questions": 题目总数,
    "phases": ["检测到的面试阶段 phase_id 列表"]
  }},
  "overall": {{
    "score": 0-10 的综合自我基准分（仅供候选人观察自己进步，不要解读为及格线）,
    "summary": "1-2 句话整体评语，口语化，不要书面化",
    "strengths": ["3 条最突出的亮点，每条 ≤ 40 字，落在简历+JD 交集上"],
    "weaknesses": ["3 条最需改进的地方，每条 ≤ 40 字，具体到知识点或表达层面"],
    "key_growth_areas": [
      {{
        "area": "具体能力领域（如 '分布式一致性' / 'STAR 表达' / 'Redis 失效策略'）",
        "current_level": "weak | partial | good | strong",
        "next_step": "下一周可以做的具体动作 1-2 句（如 '读 MIT 6.824 lec 7 关于 Raft 选举'）"
      }}
    ]
  }},
  "phase_summary": [
    {{
      "phase": "阶段 phase_id",
      "phase_name": "阶段中文名",
      "score": 该阶段平均分（0-10）,
      "question_count": 该阶段题目数,
      "summary": "该阶段表现要点 1-2 句"
    }}
  ],
  "skill_radar": {{
    "系统设计": 0-10, "编码能力": 0-10,
    "基础知识": 0-10, "沟通表达": 0-10, "项目经验": 0-10
  }}
}}

要求：
- key_growth_areas 至少 2 条，最多 4 条。这是用户最在意的部分 —— 要具体可执行，不要"加强基础"这种空话。
- strengths / weaknesses 不要重复 phase_summary 已经讲的，去重。
- 所有文本中文，口语化但保持专业。
"""

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

    # Reuse the cached prefix the analyzer already paid for in the batch
    # prompts. Full resume + JD; DeepSeek cache eats it.
    resume_for_prefix = (resume_context or "")[:16000]
    jd_for_prefix = (jd_context or "")[:8000]

    prompt = _SYNTHESIS_PROMPT.format(
        resume_context=resume_for_prefix,
        jd_context=jd_for_prefix,
        per_question_summary="\n\n".join(summary_lines),
    )

    try:
        response = await Settings.llm.acomplete(prompt)
        synthesis = _clean_json_response(response.text)
        overall_in = synthesis.get("overall") or {}

        return {
            "interview_metadata": synthesis.get("interview_metadata", {
                "total_questions": len(per_question_results),
                "phases": list({pq.get("phase", "general") for pq in per_question_results}),
            }),
            "overall": {
                "score": float(overall_in.get("score", 0) or 0),
                "summary": str(overall_in.get("summary", "") or "").strip(),
                "strengths": overall_in.get("strengths", []) or [],
                "weaknesses": overall_in.get("weaknesses", []) or [],
                "key_growth_areas": overall_in.get("key_growth_areas", []) or [],
            },
            "phase_summary": synthesis.get("phase_summary", []),
            "per_question": per_question_results,
            "skill_radar": synthesis.get("skill_radar", {}),
        }
    except Exception as exc:
        logger.error("Report synthesis failed: %s", exc)
        # Fallback: aggregate scores by phase, no key_growth_areas
        scores = [pq["score"] for pq in per_question_results if pq["score"] > 0]
        avg_score = sum(scores) / len(scores) if scores else 0.0
        return {
            "interview_metadata": {
                "total_questions": len(per_question_results),
                "phases": list({pq.get("phase", "general") for pq in per_question_results}),
            },
            "overall": {
                "score": round(avg_score, 1),
                "summary": "综合报告生成失败，仅提供逐题分析结果。",
                "strengths": [],
                "weaknesses": [],
                "key_growth_areas": [],
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
                    "score": 0,
                    "summary": "无法从转录文本中识别出有效的问答对。",
                    "strengths": [], "weaknesses": [], "key_growth_areas": [],
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
            "Stage 3 complete: overall score %.1f.",
            report.get("overall", {}).get("score", 0),
        )

        return report

    except Exception as e:
        logger.error(f"Analysis pipeline failed: {e}")
        raise


# ══════════════════════════════════════════════════════════════════════════
# Mock-specific batched analyzer
# ══════════════════════════════════════════════════════════════════════════
# When the QA pairs come from a mock interview (already structured, no ASR
# noise, grounding_refs known), we can do better than the upload pipeline:
#   - batch_size questions per LLM call (token-efficient)
#   - explicit prev / next sliding window so each question sees neighbours
# The output shape matches `_analyze_single_question`, so `_synthesize_report`
# can consume it unchanged.

_BATCH_PROMPT_PREFIX = """你是一位严格但建设性的资深技术面试官，正在对一场面试的结果做细致复盘。
所有判断必须基于下面这位候选人的简历 + 目标岗位 JD。

═════════ 候选人简历（全文） ═════════
{resume_context}

═════════ 目标岗位 JD（全文） ═════════
{jd_context}

═════════ 复盘任务说明 ═════════
请对【本批待评分】中的每道题打分并点评，**只评本批的题**，前后窗口仅作上下文参考。

【分阶段评分维度】（按本题的 phase 选用，各维度 0-2.5 分，总分 0-10）
- technical / resume_deep_dive:
    技术准确性 / 深度（不止描述还讲了原理或权衡） / 边界考虑（失败 case、限制、替代方案） / 表达清晰
- behavioral:
    Situation 背景具体（时间、团队、规模） /
    Task 自己角色明确 /
    Action 具体动作（不是「我们」糊弄） /
    Result 量化或可验证的结果
- self_intro / reverse_qa:
    采用单维度宽松打分（结构清晰 / 信息完整 / 表达自然）

如果一道题携带 `prior_quality` 字段（由 Runtime Director 在面试进行时打的标签：weak/partial/good/strong），
**作为参考先验**，但不要直接复制 —— 你看到完整的简历和 JD，可以给更准确的分数。
"""

_BATCH_PROMPT = _BATCH_PROMPT_PREFIX + """
【前置上下文（只读，不评分）】
{prev_ctx}

【本批待评分】
{batch_block}

【后置上下文（只读，不评分）】
{next_ctx}

输出严格 JSON：
{{
  "results": [
    {{
      "index": 本批中的题目序号（用 index 字段原样回传）,
      "score": 0-10,
      "critique": "200 字以内的点评，按上面对应 phase 的维度分点指出缺陷与亮点",
      "improved_answer": "更完整、更严谨的参考答案",
      "tags": ["知识点1", "标签2"]
    }}
  ]
}}"""


def _render_qa_block(qa: dict[str, Any], label: str) -> str:
    topic = qa.get("topic") or ""
    prior = qa.get("prior_quality") or qa.get("answer_quality") or {}
    prior_str = ""
    if isinstance(prior, dict) and prior.get("level"):
        prior_str = f", prior_quality={prior['level']}"
    elif isinstance(prior, str) and prior:
        prior_str = f", prior_quality={prior}"
    topic_str = f", topic={topic}" if topic else ""
    return (
        f"{label} [index={qa['index']}, phase={qa.get('phase', 'general')}{topic_str}{prior_str}]\n"
        f"  问: {qa['question'][:600]}\n"
        f"  答: {qa['answer'][:1200]}"
    )


async def _analyze_batch(
    batch: list[dict[str, Any]],
    prev_window: list[dict[str, Any]],
    next_window: list[dict[str, Any]],
    *,
    resume_context: str,
    jd_context: str,
) -> list[dict[str, Any]]:
    # NOTE: the prefix is intentionally fed FULL resume + JD (truncating to a
    # massive 16k each, well within DeepSeek's 1M context). That cost is one
    # cache miss on the first batch — every subsequent batch in the same finish
    # call hits the prompt cache on the prefix prefix and pays only for the
    # dynamic tail.
    resume_for_prefix = (resume_context or "")[:16000]
    jd_for_prefix = (jd_context or "")[:8000]

    prev_ctx = "\n\n".join(_render_qa_block(q, "[前]") for q in prev_window) or "（无）"
    next_ctx = "\n\n".join(_render_qa_block(q, "[后]") for q in next_window) or "（无）"
    batch_block = "\n\n".join(_render_qa_block(q, "[本批]") for q in batch)

    prompt = _BATCH_PROMPT.format(
        resume_context=resume_for_prefix,
        jd_context=jd_for_prefix,
        prev_ctx=prev_ctx,
        next_ctx=next_ctx,
        batch_block=batch_block,
    )

    # Default fallback: 0-score entries for each QA in the batch.
    def _fallback() -> list[dict[str, Any]]:
        return [
            {
                "index": q["index"],
                "phase": q.get("phase", "general"),
                "question": q["question"],
                "answer": q["answer"],
                "score": 0,
                "critique": "分析失败",
                "improved_answer": "",
                "tags": [],
            }
            for q in batch
        ]

    try:
        response = await Settings.llm.acomplete(prompt)
        parsed = _clean_json_response(response.text)
        items_in = parsed.get("results") if isinstance(parsed, dict) else None
        if not isinstance(items_in, list):
            logger.warning("Batched analyzer returned non-list results; falling back")
            return _fallback()

        by_index: dict[int, dict[str, Any]] = {}
        for item in items_in:
            if not isinstance(item, dict):
                continue
            try:
                idx = int(item.get("index"))
            except (TypeError, ValueError):
                continue
            by_index[idx] = item

        out: list[dict[str, Any]] = []
        for q in batch:
            item = by_index.get(int(q["index"]))
            if item is None:
                # LLM dropped this one — single-shot retry inline.
                logger.warning("Batched analyzer skipped Q%s; falling back to per-question", q["index"])
                out.append(
                    await _analyze_single_question(
                        q,
                        context_text="",
                        total_questions=len(batch),
                        resume_context=resume_context,
                        jd_context=jd_context,
                    )
                )
                continue
            out.append({
                "index": q["index"],
                "phase": q.get("phase", "general"),
                "question": q["question"],
                "answer": q["answer"],
                "score": float(item.get("score", 0) or 0),
                "critique": str(item.get("critique", "")).strip(),
                "improved_answer": str(item.get("improved_answer", "")).strip(),
                "tags": item.get("tags", []) if isinstance(item.get("tags"), list) else [],
            })
        return out
    except Exception as exc:  # noqa: BLE001
        logger.error("Batched analyzer failed; falling back: %s", exc)
        return _fallback()


async def analyze_mock_qa_batched(
    qa_pairs: list[dict[str, Any]],
    *,
    resume_context: str = "",
    jd_context: str = "",
    batch_size: int = 2,
    ctx_prev: int = 3,
    ctx_next: int = 2,
) -> dict[str, Any]:
    """Run the full mock-source pipeline: batched per-question scoring with a
    sliding window, then global synthesis. Returns the same v2 report shape as
    `analyze_interview`."""
    # Normalize incoming entries to the {index, question, answer, phase} shape
    # the rest of this module expects (1-based index, ordered by appearance).
    # We additionally carry forward Runtime Director metadata (topic + the
    # in-flight quality label) so the analyzer prompt can surface it to the LLM.
    normalized: list[dict[str, Any]] = []
    for i, pair in enumerate(qa_pairs, start=1):
        if not isinstance(pair, dict):
            continue
        normalized.append({
            "index": i,
            "phase": pair.get("phase") or "general",
            "question": str(pair.get("question") or ""),
            "answer": str(pair.get("answer") or ""),
            "is_follow_up": bool(pair.get("is_follow_up", False)),
            "grounding_refs": pair.get("grounding_refs") or [],
            "topic": pair.get("topic"),
            "prior_quality": pair.get("answer_quality"),
        })

    if not normalized:
        return {
            "interview_metadata": {"total_questions": 0, "phases": []},
            "overall": {
                "score": 0,
                "summary": "面试无问答记录。",
                "strengths": [], "weaknesses": [], "key_growth_areas": [],
            },
            "phase_summary": [],
            "per_question": [],
            "skill_radar": {},
        }

    # Walk in batch_size strides, schedule batches concurrently.
    tasks: list[asyncio.Task] = []
    for start in range(0, len(normalized), batch_size):
        end = min(start + batch_size, len(normalized))
        batch = normalized[start:end]
        prev_window = normalized[max(0, start - ctx_prev):start]
        next_window = normalized[end:end + ctx_next]
        tasks.append(
            asyncio.create_task(
                _analyze_batch(
                    batch,
                    prev_window,
                    next_window,
                    resume_context=resume_context,
                    jd_context=jd_context,
                )
            )
        )

    batched_results = await asyncio.gather(*tasks)
    per_question_results: list[dict[str, Any]] = [r for chunk in batched_results for r in chunk]

    logger.info(
        "Mock batched analysis complete: %d questions across %d batches (size=%d, prev=%d, next=%d)",
        len(per_question_results),
        len(tasks),
        batch_size,
        ctx_prev,
        ctx_next,
    )

    report = await _synthesize_report(
        per_question_results,
        resume_context=resume_context,
        jd_context=jd_context,
    )
    return report


__all__ = ["analyze_interview", "analyze_mock_qa_batched", "extract_qa_pairs_with_llm"]
