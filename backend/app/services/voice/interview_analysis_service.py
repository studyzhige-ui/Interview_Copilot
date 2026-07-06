"""Interview transcript analysis — three-stage MapReduce pipeline.

Architecture:
  Stage 0: WhisperX transcription (handled by audio_transcription_service)
  Stage 1: Full LLM QA extraction (role identification, pairing, tagging)
  Stage 2: Per-question deep analysis (Map) with sliding context window
  Stage 3: Global synthesis report (Reduce)

Design principles:
  - LLM reads numbered transcript lines and returns QA line-spans; code slices the original text
  - Handles speaker diarization failures, mixed turns, short/long exchanges
  - Long transcripts are chunked with overlap and deduplicated
  - Each question is analyzed with a 3-question sliding context window
  - Resume and JD context are injected into every analysis stage
"""

import asyncio
import json
import logging
import re
from typing import Any, Callable

import tiktoken


from llama_index.core.llms import LLM

from app.core.llm_client_factory import get_llm_for_role

logger = logging.getLogger(__name__)

def _notify_progress(on_progress, n: int) -> None:
    """Best-effort progress ping — a broken callback (it's a DB write) must
    never fail the analysis, but a persistently failing one silently freezes
    the SSE percent at the band floor, hence WARNING not DEBUG."""
    if on_progress is None:
        return
    try:
        on_progress(n)
    except Exception:  # noqa: BLE001
        logger.warning("on_progress callback failed", exc_info=True)


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
[硬性约束] 全部输出使用简体中文。即便原始转录里出现繁体字、英文术语，最终回复也用简体中文表达（专有名词、代码标识符保留原文）。

你是一名专业的面试对话分析专家。下面是一场面试录音的语音转录文本（ASR 输出，可能有错别字和口语化表达）。**每一行都带有行号标签（如 L12|）。**

转录文本：
---
{transcript}
---

{resume_hint}

你的任务：仔细阅读整段对话，从中提取面试官与候选人之间的所有问答交互（QA pairs）。**不要复述原文** —— 对每个问答对，只输出它覆盖的行号区间，系统会用行号切回原文。

提取规则：
1. **角色识别**：根据对话内容判断谁是面试官（提问方）、谁是候选人（回答方）。
2. **问题区间**：question_lines 覆盖面试官就这个话题说的所有行（包括评论、过渡、闲聊）。
3. **回答区间**：answer_lines 覆盖候选人针对该话题的所有行。如果回答被打断后继续，用多个区间表示（例如 [[5,8],[10,12]]）。
4. **追问识别**：如果面试官针对候选人的某个回答继续追问，标记 is_follow_up 并在 parent_qa_index 关联原始问题的序号（从 1 开始）。
5. **区间必须来自给出的行号**，不要发明行号；同一行可以同时属于相邻问答对（例如一句话既是回应又是新问题）。
6. **问题概括**：question_summary 用一句简短的话概括这道题/话题的核心内容（15字以内）。

输出纯 JSON，不要任何解释文字：
{{
  "qa_pairs": [
    {{
      "question_lines": [[3, 4]],
      "answer_lines": [[5, 9]],
      "question_summary": "简短概括",
      "phase": "self_intro 或 resume_deep_dive 或 technical 或 behavioral 或 reverse_qa 或 general",
      "is_follow_up": false,
      "parent_qa_index": null
    }}
  ]
}}"""


async def extract_qa_pairs_with_llm(
    transcript: str,
    resume_context: str = "",
    *,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    """Stage 1: LLM-powered QA extraction over NUMBERED transcript lines.

    The LLM identifies speaker roles / phases / follow-up chains but returns
    only line-span indices per pair (ANA-2); code slices the original
    transcript, so wording fidelity is exact by construction and output size
    is independent of recording length. Very long transcripts are split into
    overlapping line chunks with global numbering and merged.
    """
    if not transcript or not transcript.strip():
        logger.warning("Empty transcript provided.")
        return []

    # ANA-2: the LLM outputs LINE SPANS, not verbatim text — a 60-minute
    # recording used to require ~20k output tokens (over every model's
    # output cap → truncated JSON → empty report at status=completed).
    # Spans keep the output a few hundred tokens regardless of length,
    # and the original wording is preserved exactly by construction.
    lines = [ln for ln in transcript.split("\n") if ln.strip()]
    # +3/line ≈ the "L{n}|" prefixes the prompt adds — near the threshold an
    # uncounted prefix on thousands of lines could push past the context cap.
    token_count = _count_tokens(transcript) + 3 * len(lines)
    logger.info("Stage 1: transcript has %d tokens / %d lines.", token_count, len(lines))

    # Resolve the owner's utility LLM ONCE and thread the instance down --
    # per-chunk re-resolution would re-hit the credential lookup for every
    # chunk (MDL-1: the owner's selection/keys drive background analysis).
    llm = get_llm_for_role("utility", user_id=user_id)
    if token_count <= _EXTRACTION_MAX_TOKENS:
        return _strip_span_bookkeeping(
            await _extract_single_pass(lines, resume_context, llm=llm)
        )

    # Chunked extraction for very long transcripts
    return await _extract_chunked(lines, resume_context, token_count, llm=llm)


async def _extract_single_pass(
    lines: list[str],
    resume_context: str = "",
    *,
    llm: LLM,
    line_offset: int = 0,
) -> list[dict[str, Any]]:
    """Extract QA pairs from ``lines`` in one LLM call.

    ``line_offset`` shifts the displayed line numbers so chunked calls carry
    GLOBAL numbering — spans from any chunk index into the same full
    transcript and merging needs no per-chunk remapping.
    """
    resume_hint = ""
    if resume_context:
        resume_hint = f"候选人简历背景（辅助判断阶段和评估）：\n{resume_context[:1500]}"

    numbered = "\n".join(
        f"L{line_offset + i}|{ln}" for i, ln in enumerate(lines, start=1)
    )
    prompt = _LLM_EXTRACTION_PROMPT.format(
        transcript=numbered,
        resume_hint=resume_hint,
    )

    try:
        response = await llm.acomplete(
            prompt,
            response_format={"type": "json_object"},
        )
        result = _clean_json_response(response.text)
        raw_pairs = result.get("qa_pairs", [])

        if not raw_pairs:
            logger.warning("LLM returned empty qa_pairs.")
            return []

        qa_pairs = _resolve_span_pairs(
            raw_pairs, lines, line_offset=line_offset,
        )
        logger.info("Stage 1 complete: extracted %d QA pairs.", len(qa_pairs))
        return qa_pairs

    except Exception as exc:
        logger.error("LLM QA extraction failed: %s", exc)
        return []


async def _extract_chunked(
    lines: list[str],
    resume_context: str,
    total_tokens: int,
    *,
    llm: LLM,
) -> list[dict[str, Any]]:
    """Extract QA pairs from a very long transcript in line chunks.

    Chunks carry GLOBAL line numbering (via ``line_offset``), so returned
    spans all index into the same transcript. Overlap gives the model
    context across the boundary; pairs whose question starts inside a
    region already covered by an earlier chunk are dropped (span-based
    dedup — the old text-similarity dedup retired with ANA-2).
    """
    chunk_limit = _EXTRACTION_MAX_TOKENS - 5000  # reserve space for prompt
    overlap_lines = 10

    chunks: list[tuple[int, list[str]]] = []  # (0-based global start, lines)
    cur_start = 0
    cur: list[str] = []
    cur_tokens = 0
    for i, ln in enumerate(lines):
        ln_tokens = _count_tokens(ln)
        if cur_tokens + ln_tokens + 3 > chunk_limit and cur:
            chunks.append((cur_start, cur))
            keep = cur[-overlap_lines:]
            cur_start = i - len(keep)
            cur = list(keep)
            cur_tokens = sum(_count_tokens(x) for x in keep)
        cur.append(ln)
        cur_tokens += ln_tokens
    if cur:
        chunks.append((cur_start, cur))

    logger.info(
        "Stage 1: splitting %d-token transcript into %d line chunks.",
        total_tokens, len(chunks),
    )

    all_pairs: list[dict[str, Any]] = []
    # Highest QUESTION end line claimed by an accepted pair. Dedup keys on
    # question spans only: an answer that ran past a chunk boundary must not
    # block the next chunk's FULLER version of the same pair.
    covered_q_until = 0
    for ci, (start0, chunk_lines) in enumerate(chunks):
        chunk_pairs = await _extract_single_pass(
            chunk_lines, resume_context, llm=llm, line_offset=start0,
        )
        for pair in chunk_pairs:
            pair["_chunk"] = ci
        kept = 0
        for pair in chunk_pairs:
            if ci > 0 and pair.get("_q_start", 0) <= covered_q_until:
                # A previously accepted pair already claims this question.
                # If this version extends further (its answer was cut at the
                # previous chunk's window edge), prefer it over the stub.
                prev = all_pairs[-1] if all_pairs else None
                if (
                    prev is not None
                    and pair.get("_q_start") == prev.get("_q_start")
                    and pair.get("_end_line", 0) > prev.get("_end_line", 0)
                ):
                    all_pairs[-1] = pair
                    covered_q_until = max(covered_q_until, pair.get("_q_end", 0))
                continue
            all_pairs.append(pair)
            covered_q_until = max(covered_q_until, pair.get("_q_end", 0))
            kept += 1
        logger.info(
            "Stage 1 chunk %d/%d: extracted %d pairs, kept %d.",
            ci + 1, len(chunks), len(chunk_pairs), kept,
        )

    # Cross-chunk parent links can't survive the merge (each chunk numbers
    # its own output) — the in-chunk remap already happened in
    # _resolve_span_pairs; renumber globally and keep parent links only
    # when parent and child were kept from the same chunk.
    old_to_new = {
        (pair.get("_chunk"), pair["index"]): i
        for i, pair in enumerate(all_pairs, start=1)
    }
    for i, pair in enumerate(all_pairs, start=1):
        parent = pair.get("parent_index")
        pair["parent_index"] = (
            old_to_new.get((pair.get("_chunk"), parent)) if parent else None
        )
        pair["index"] = i
    _strip_span_bookkeeping(all_pairs)
    logger.info("Stage 1 complete: %d QA pairs after span dedup.", len(all_pairs))
    return all_pairs


def _strip_span_bookkeeping(pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop the chunk-merge bookkeeping keys before pairs leave extraction."""
    for pair in pairs:
        for key in ("_start_line", "_end_line", "_q_start", "_q_end", "_chunk"):
            pair.pop(key, None)
    return pairs


def _coerce_ranges(value: Any) -> list[tuple[int, int]]:
    """Accept ``[s, e]`` or ``[[s, e], ...]`` (ints or numeric strings);
    reject anything else. Returned ranges are 1-based inclusive."""
    if not isinstance(value, list) or not value:
        return []
    if all(isinstance(v, (int, float, str)) for v in value) and len(value) == 2:
        value = [value]
    out: list[tuple[int, int]] = []
    for item in value:
        if not isinstance(item, list) or len(item) != 2:
            continue
        try:
            s, e = int(item[0]), int(item[1])
        except (TypeError, ValueError):
            continue
        if s > e:
            s, e = e, s
        out.append((s, e))
    return out


def _slice_lines(lines: list[str], ranges: list[tuple[int, int]], line_offset: int) -> str:
    """Join the transcript lines covered by ``ranges`` (global 1-based,
    clamped to the chunk's own window)."""
    lo, hi = line_offset + 1, line_offset + len(lines)
    picked: list[str] = []
    for s, e in ranges:
        s, e = max(s, lo), min(e, hi)
        for n in range(s, e + 1):
            picked.append(lines[n - line_offset - 1])
    return "\n".join(picked).strip()


def _resolve_span_pairs(
    raw_pairs: list[dict], lines: list[str], *, line_offset: int = 0,
) -> list[dict[str, Any]]:
    """Turn LLM span output into the pipeline's QA-pair shape by slicing
    the ORIGINAL transcript lines (high fidelity by construction)."""
    qa_pairs: list[dict[str, Any]] = []
    # The LLM's parent_qa_index refers to ITS 1-based output ordering;
    # invalid-span pairs get dropped below, so remap ordinals → final
    # indices (a stale ordinal used to point 追问 context at the wrong
    # question).
    ordinal_to_new: dict[int, int] = {}
    parents_raw: list[Any] = []
    for ordinal, rp in enumerate(raw_pairs, start=1):
        if not isinstance(rp, dict):
            continue
        q_ranges = _coerce_ranges(rp.get("question_lines"))
        a_ranges = _coerce_ranges(rp.get("answer_lines"))
        question = _slice_lines(lines, q_ranges, line_offset)
        answer = _slice_lines(lines, a_ranges, line_offset)
        if not question or not answer:
            continue
        if len(question) < 5 and len(answer) < 5:
            continue
        span_points = [n for s, e in q_ranges + a_ranges for n in (s, e)]
        q_points = [n for s, e in q_ranges for n in (s, e)]
        ordinal_to_new[ordinal] = len(qa_pairs) + 1
        parents_raw.append(rp.get("parent_qa_index"))
        qa_pairs.append({
            "index": len(qa_pairs) + 1,
            "question": question,
            "answer": answer,
            "question_summary": str(rp.get("question_summary", "")).strip(),
            "phase": str(rp.get("phase", "general")).strip(),
            "is_follow_up": bool(rp.get("is_follow_up", False)),
            "parent_index": None,  # remapped below
            # Chunk-merge bookkeeping (stripped before the pairs leave
            # extraction).
            "_start_line": min(span_points) if span_points else 0,
            "_end_line": max(span_points) if span_points else 0,
            "_q_start": min(q_points) if q_points else 0,
            "_q_end": max(q_points) if q_points else 0,
        })
    for pair, parent_raw in zip(qa_pairs, parents_raw):
        try:
            pair["parent_index"] = ordinal_to_new.get(int(parent_raw)) if parent_raw else None
        except (TypeError, ValueError):
            pair["parent_index"] = None
    return qa_pairs


_ANALYSIS_MAX_ATTEMPTS = 2
_ANALYSIS_RETRY_BASE_S = 2.0
# Upload path fans out one task per question; without a bound a 30-question
# interview fires 30 concurrent completions — a rate-limit trigger on most
# providers. 5 keeps the pipeline fast without tripping vendor limits.
_ANALYSIS_MAX_CONCURRENCY = 5


async def _acomplete_json_with_retry(llm: LLM, prompt: str) -> dict[str, Any]:
    """One grading call: JSON mode + bounded retry with backoff.

    Raises the last exception after ``_ANALYSIS_MAX_ATTEMPTS`` — the caller
    decides what a failed question looks like (score=None, 未评分).
    """
    last_exc: Exception | None = None
    for attempt in range(1, _ANALYSIS_MAX_ATTEMPTS + 1):
        try:
            response = await llm.acomplete(
                prompt, response_format={"type": "json_object"},
            )
            return _clean_json_response(response.text)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < _ANALYSIS_MAX_ATTEMPTS:
                await asyncio.sleep(_ANALYSIS_RETRY_BASE_S * attempt)
    raise last_exc  # type: ignore[misc]


# ══════════════════════════════════════════════════════════════════════════
# Stage 2: Per-Question Deep Analysis (Map) with Sliding Context Window
# ══════════════════════════════════════════════════════════════════════════

_SLIDING_WINDOW_SIZE = 3  # include up to 3 preceding QA pairs

_PER_QUESTION_PROMPT = """\
[硬性约束] 全部输出使用简体中文。即便原始转录里出现繁体字、英文术语，最终回复也用简体中文表达（专有名词、代码标识符保留原文）。

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
    *,
    llm: LLM,
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
        result = await _acomplete_json_with_retry(llm, prompt)

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
        # ANA-6: a failed grading is 未评分 (score=None), never a silent 0 —
        # zeros were averaged into the overall verdict as if the candidate
        # had bombed the question.
        logger.error("Per-question analysis failed for Q%d: %s", qa_pair["index"], exc)
        return {
            "index": qa_pair["index"],
            "phase": qa_pair.get("phase", "general"),
            "question": qa_pair["question"],
            "answer": qa_pair["answer"],
            "score": None,
            "critique": "该题分析失败（模型调用异常），未计入总分。",
            "improved_answer": "",
            "tags": [],
            "analysis_failed": True,
        }


# ══════════════════════════════════════════════════════════════════════════
# Stage 3: Global Synthesis Report (Reduce)
# ══════════════════════════════════════════════════════════════════════════

_SYNTHESIS_PROMPT = """\
[硬性约束] 全部输出使用简体中文。即便原始转录里出现繁体字、英文术语，最终回复也用简体中文表达（专有名词、代码标识符保留原文）。

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
    *,
    llm: LLM,
) -> dict[str, Any]:
    """Stage 3: Synthesize per-question results into a global report."""

    # Build per-question summary for the synthesis prompt. Failed (未评分)
    # questions are excluded — their placeholder critique would poison the
    # synthesis — and reported via failed_count instead (ANA-6).
    graded = [pq for pq in per_question_results if not pq.get("analysis_failed")]
    failed_count = len(per_question_results) - len(graded)
    if per_question_results and not graded:
        # Every grading call failed (e.g. broken provider auth) — asking the
        # synthesis LLM to write a verdict from just resume+JD would invent
        # one. Return an honest empty report instead.
        return {
            "interview_metadata": {
                "total_questions": len(per_question_results),
                "phases": list({pq.get("phase", "general") for pq in per_question_results}),
                "failed_count": failed_count,
            },
            "overall": {
                "score": 0,
                "summary": "全部题目的分析调用都失败了（模型服务异常），未能生成综合报告，请重试。",
                "strengths": [], "weaknesses": [], "key_growth_areas": [],
            },
            "phase_summary": [],
            "per_question": per_question_results,
            "skill_radar": {},
        }
    summary_lines: list[str] = []
    for pq in graded:
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
        response = await llm.acomplete(prompt)
        synthesis = _clean_json_response(response.text)
        overall_in = synthesis.get("overall") or {}

        meta = synthesis.get("interview_metadata") or {
            "total_questions": len(per_question_results),
            "phases": list({pq.get("phase", "general") for pq in per_question_results}),
        }
        meta["failed_count"] = failed_count
        return {
            "interview_metadata": meta,
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
        # Fallback: aggregate scores by phase, no key_growth_areas.
        # None scores (未评分) are excluded, not treated as zeros.
        scores = [pq["score"] for pq in graded if (pq.get("score") or 0) > 0]
        avg_score = sum(scores) / len(scores) if scores else 0.0
        return {
            "interview_metadata": {
                "total_questions": len(per_question_results),
                "phases": list({pq.get("phase", "general") for pq in per_question_results}),
                "failed_count": failed_count,
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
    on_progress: Callable[[int], None] | None = None,
    user_id: str | None = None,
    qa_pairs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Analyze an interview transcript using the three-stage MapReduce pipeline.

    Args:
        transcript: WhisperX diarized transcript (Markdown format)
        resume_context: Plain text resume content (recommended)
        jd_context: Plain text job description (optional)
        on_progress: optional callback invoked with the number of questions
            just completed (per-question during Stage 2). The orchestrator
            wires this to ``increment_analyzed_count`` so the SSE progress
            stream reports REAL per-question progress. Exceptions from the
            callback are swallowed — progress must never fail an analysis.

    Returns:
        Complete analysis report dict matching the v2 report schema.
    """
    try:
        # ── Stage 1: LLM-powered QA extraction ──────────────────────
        # ANA-1: the orchestrator already ran Stage 1 (and persisted the QA
        # shells from ITS result) — re-extracting here was a second full LLM
        # pass whose independently-sampled pairs could mismatch the shells
        # (order_idx backfill then attaches analyses to the wrong questions).
        if qa_pairs is None:
            qa_pairs = await extract_qa_pairs_with_llm(
                transcript, resume_context, user_id=user_id,
            )

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
        # Owner's primary model drives scoring + synthesis (MDL-1);
        # resolved once, shared by every concurrent question task.
        analysis_llm = get_llm_for_role("primary", user_id=user_id)
        # ANA-6: bound the fan-out — 30 questions used to mean 30 concurrent
        # completions, a guaranteed rate-limit trip on most providers.
        semaphore = asyncio.Semaphore(_ANALYSIS_MAX_CONCURRENCY)

        async def _run_one(pair: dict[str, Any], idx: int) -> dict[str, Any]:
            async with semaphore:
                context_text = _build_sliding_context(qa_pairs, idx)
                res = await _analyze_single_question(
                    qa_pair=pair,
                    context_text=context_text,
                    total_questions=len(qa_pairs),
                    resume_context=resume_context,
                    jd_context=jd_context,
                    llm=analysis_llm,
                )
            _notify_progress(on_progress, 1)
            return res

        tasks = [
            asyncio.create_task(_run_one(pair, idx))
            for idx, pair in enumerate(qa_pairs)
        ]
        per_question_results = await asyncio.gather(*tasks)
        per_question_results = list(per_question_results)

        logger.info("Stage 2 complete: analyzed %d questions.", len(per_question_results))

        # ── Stage 3: Global synthesis (Reduce) ───────────────────────
        report = await _synthesize_report(
            per_question_results,
            resume_context=resume_context,
            jd_context=jd_context,
            llm=analysis_llm,
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
# noise), we can do better than the upload pipeline:
#   - batch_size questions per LLM call (token-efficient)
#   - explicit prev / next sliding window so each question sees neighbours
# The output shape matches `_analyze_single_question`, so `_synthesize_report`
# can consume it unchanged.

_BATCH_PROMPT_PREFIX = """[硬性约束] 全部输出使用简体中文。即便原始转录里出现繁体字、英文术语，最终回复也用简体中文表达（专有名词、代码标识符保留原文）。

你是一位严格但建设性的资深技术面试官，正在对一场面试的结果做细致复盘。
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

如果一道题携带 `prior_quality` 字段（面试过程中预先标注的质量标签：weak/partial/good/strong），
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
    llm: LLM,
) -> list[dict[str, Any]]:
    # NOTE: the prefix is intentionally fed FULL resume + JD (truncated to
    # 16k/8k). Batches fire concurrently (bounded by the semaphore), so the
    # shared prefix does NOT reliably hit the provider prompt cache — the
    # first wave all miss; only batches scheduled after one completes can
    # hit. The stable prefix still helps: retries and the synthesis call
    # reuse it, and providers with racy cache insertion catch some of it.
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

    # Failed batch → 未评分 entries (score=None), not zeros (ANA-6).
    def _fallback() -> list[dict[str, Any]]:
        return [
            {
                "index": q["index"],
                "phase": q.get("phase", "general"),
                "question": q["question"],
                "answer": q["answer"],
                "score": None,
                "critique": "该题分析失败（模型调用异常），未计入总分。",
                "improved_answer": "",
                "tags": [],
                "analysis_failed": True,
            }
            for q in batch
        ]

    try:
        parsed = await _acomplete_json_with_retry(llm, prompt)
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
                        llm=llm,
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
    on_progress: Callable[[int], None] | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Run the full mock-source pipeline: batched per-question scoring with a
    sliding window, then global synthesis. Returns the same v2 report shape as
    `analyze_interview`.

    ``on_progress`` (optional): called with the number of questions completed
    after each batch — see ``analyze_interview`` for the contract."""
    # Normalize incoming entries to the {index, question, answer, phase} shape
    # the rest of this module expects (1-based index, ordered by appearance).
    # We additionally carry forward any optional per-QA metadata (topic + a
    # prior quality label, when present) so the analyzer prompt can surface it.
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

    # Owner's primary model drives scoring + synthesis (MDL-1).
    analysis_llm = get_llm_for_role("primary", user_id=user_id)
    # Bounded fan-out (ANA-6) — same rationale as the upload path.
    semaphore = asyncio.Semaphore(_ANALYSIS_MAX_CONCURRENCY)

    # Walk in batch_size strides, schedule batches concurrently.
    async def _run_batch(
        batch: list[dict[str, Any]],
        prev_window: list[dict[str, Any]],
        next_window: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        async with semaphore:
            chunk = await _analyze_batch(
                batch,
                prev_window,
                next_window,
                resume_context=resume_context,
                jd_context=jd_context,
                llm=analysis_llm,
            )
        _notify_progress(on_progress, len(chunk))
        return chunk

    tasks: list[asyncio.Task] = []
    for start in range(0, len(normalized), batch_size):
        end = min(start + batch_size, len(normalized))
        batch = normalized[start:end]
        prev_window = normalized[max(0, start - ctx_prev):start]
        next_window = normalized[end:end + ctx_next]
        tasks.append(asyncio.create_task(_run_batch(batch, prev_window, next_window)))

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
        llm=analysis_llm,
    )
    return report


__all__ = ["analyze_interview", "analyze_mock_qa_batched", "extract_qa_pairs_with_llm"]
