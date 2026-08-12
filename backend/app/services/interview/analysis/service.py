"""Interview transcript extraction, scoring, and synthesis pipeline.

Architecture:
  Stage 0: WhisperX transcription (handled by audio_transcription_service)
  Stage 1: Full LLM QA extraction (role identification, pairing, tagging)
  Stage 2: Batched question analysis with neighbouring context
  Stage 3: Deterministic score aggregation + narrative synthesis

Design principles:
  - LLM reads numbered transcript lines and returns QA line-spans; code slices the original text
  - Handles speaker diarization failures, mixed turns, short/long exchanges
  - Long transcripts are chunked with overlap and deduplicated
  - Upload and mock sources share exactly one batched scoring path
  - Resume and JD context are injected into every analysis stage
"""

import asyncio
import json
import logging
import math
from typing import Any, Callable

import tiktoken
from llama_index.core.llms import LLM

from app.core.llm_client_factory import get_internal_llm, get_llm_for_role
from app.prompts.voice_analysis import (
    QA_EXTRACTION_PROMPT,
    QUESTION_ANALYSIS_PROMPT,
    SYNTHESIS_PROMPT,
)

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
    logger.info(
        "Stage 1: transcript has %d tokens / %d lines.", token_count, len(lines)
    )

    # Resolve the platform worker LLM once and thread the instance down.
    # per-chunk re-resolution would re-hit the credential lookup for every
    # chunk (MDL-1: the owner's selection/keys drive background analysis).
    llm = get_internal_llm("worker")
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
    prompt = QA_EXTRACTION_PROMPT.format(
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
            raw_pairs,
            lines,
            line_offset=line_offset,
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
        total_tokens,
        len(chunks),
    )

    all_pairs: list[dict[str, Any]] = []
    # Highest QUESTION end line claimed by an accepted pair. Dedup keys on
    # question spans only: an answer that ran past a chunk boundary must not
    # block the next chunk's FULLER version of the same pair.
    covered_q_until = 0
    for ci, (start0, chunk_lines) in enumerate(chunks):
        chunk_pairs = await _extract_single_pass(
            chunk_lines,
            resume_context,
            llm=llm,
            line_offset=start0,
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
            ci + 1,
            len(chunks),
            len(chunk_pairs),
            kept,
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


def _slice_lines(
    lines: list[str], ranges: list[tuple[int, int]], line_offset: int
) -> str:
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
    raw_pairs: list[dict],
    lines: list[str],
    *,
    line_offset: int = 0,
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
        qa_pairs.append(
            {
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
            }
        )
    for pair, parent_raw in zip(qa_pairs, parents_raw):
        try:
            pair["parent_index"] = (
                ordinal_to_new.get(int(parent_raw)) if parent_raw else None
            )
        except (TypeError, ValueError):
            pair["parent_index"] = None
    return qa_pairs


_ANALYSIS_MAX_ATTEMPTS = 2
_ANALYSIS_RETRY_BASE_S = 2.0
_ANALYSIS_MAX_CONCURRENCY = 5
_SKILL_DIMENSIONS = ("系统设计", "编码能力", "基础知识", "沟通表达", "项目经验")


def _validated_score(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("score must be a number or null")
    score = float(value)
    if not math.isfinite(score) or not 0 <= score <= 10:
        raise ValueError("score must be between 0 and 10")
    return round(score, 1)


def _validate_batch_result(
    payload: dict[str, Any], expected_indexes: list[int]
) -> dict[int, dict[str, Any]]:
    items = payload.get("results")
    if not isinstance(items, list) or len(items) != len(expected_indexes):
        raise ValueError("results must contain every requested question exactly once")

    parsed: dict[int, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("each result must be an object with an integer index")
        raw_index = item.get("index")
        if isinstance(raw_index, bool) or not isinstance(raw_index, int):
            raise ValueError("invalid result index")
        index = raw_index
        if index in parsed:
            raise ValueError(f"duplicate result index: {index}")
        if "score" not in item:
            raise ValueError(f"missing score for index: {index}")
        critique = item.get("critique")
        improved = item.get("improved_answer")
        tags = item.get("tags")
        if not isinstance(critique, str) or not isinstance(improved, str):
            raise ValueError(f"invalid text fields for index: {index}")
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            raise ValueError(f"invalid tags for index: {index}")
        parsed[index] = {
            "score": _validated_score(item["score"]),
            "critique": critique.strip(),
            "improved_answer": improved.strip(),
            "tags": [tag.strip() for tag in tags if tag.strip()][:5],
        }

    if set(parsed) != set(expected_indexes):
        raise ValueError("result indexes do not match the requested batch")
    return parsed


async def _request_batch_result(
    llm: LLM, prompt: str, expected_indexes: list[int]
) -> dict[int, dict[str, Any]]:
    """Retry the exact batch when either transport or output contract fails."""
    last_exc: Exception | None = None
    for attempt in range(1, _ANALYSIS_MAX_ATTEMPTS + 1):
        try:
            response = await llm.acomplete(
                prompt,
                response_format={"type": "json_object"},
            )
            return _validate_batch_result(
                _clean_json_response(response.text), expected_indexes
            )
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.warning(
                "Question-analysis batch attempt %d/%d failed: %s",
                attempt,
                _ANALYSIS_MAX_ATTEMPTS,
                exc,
            )
            if attempt < _ANALYSIS_MAX_ATTEMPTS:
                await asyncio.sleep(_ANALYSIS_RETRY_BASE_S * attempt)
    assert last_exc is not None
    raise last_exc


# ══════════════════════════════════════════════════════════════════════════
# Stage 3: Global Synthesis Report (Reduce)
# ══════════════════════════════════════════════════════════════════════════

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
    llm: LLM | None,
) -> dict[str, Any]:
    """Aggregate numeric scores in code; ask the model only for interpretation."""
    assessed = [
        pq for pq in per_question_results if isinstance(pq.get("score"), (int, float))
    ]
    scores = [float(pq["score"]) for pq in assessed]
    overall_score = round(sum(scores) / len(scores), 1) if scores else None
    failed_count = sum(bool(pq.get("analysis_failed")) for pq in per_question_results)
    phases = list(
        dict.fromkeys(str(pq.get("phase") or "general") for pq in per_question_results)
    )

    phase_rows: list[dict[str, Any]] = []
    for phase in phases:
        phase_items = [
            pq
            for pq in per_question_results
            if str(pq.get("phase") or "general") == phase
        ]
        phase_scores = [
            float(pq["score"])
            for pq in phase_items
            if isinstance(pq.get("score"), (int, float))
        ]
        phase_rows.append(
            {
                "phase": phase,
                "phase_name": _PHASE_NAME_MAP.get(phase, phase),
                "score": round(sum(phase_scores) / len(phase_scores), 1)
                if phase_scores
                else None,
                "question_count": len(phase_items),
                "summary": "本阶段没有可用评分证据。"
                if not phase_scores
                else "本阶段表现详见逐题分析。",
            }
        )

    empty_radar = {dimension: None for dimension in _SKILL_DIMENSIONS}
    if not assessed:
        if not per_question_results:
            message = "面试中没有可供分析的问答记录。"
        elif failed_count == len(per_question_results):
            message = "全部题目的分析调用都失败了，暂时无法形成可靠复盘，请重试。"
        else:
            message = "本次问答均不具备可评分的候选人回答，未生成表现分数。"
        return {
            "overall": {
                "score": None,
                "summary": message,
                "strengths": [],
                "weaknesses": [],
                "key_growth_areas": [],
            },
            "phase_summary": phase_rows,
            "per_question": per_question_results,
            "skill_radar": empty_radar,
            "tag": "",
        }

    summary_lines: list[str] = []
    for pq in assessed:
        summary_lines.append(
            f"第{pq['index']}题 [{_PHASE_NAME_MAP.get(pq.get('phase', ''), pq.get('phase', ''))}] "
            f"评分:{pq['score']}/10\n"
            f"  问题: {pq['question'][:160]}\n"
            f"  分析: {pq['critique'][:240]}\n"
            f"  标签: {', '.join(pq.get('tags', []))}"
        )

    # Reuse the cached prefix the analyzer already paid for in the batch
    # prompts. Full resume + JD; DeepSeek cache eats it.
    resume_for_prefix = (resume_context or "")[:16000]
    jd_for_prefix = (jd_context or "")[:8000]

    prompt = SYNTHESIS_PROMPT.format(
        resume_context=resume_for_prefix,
        jd_context=jd_for_prefix,
        per_question_summary="\n\n".join(summary_lines),
    )

    try:
        assert llm is not None
        response = await llm.acomplete(
            prompt,
            response_format={"type": "json_object"},
        )
        synthesis = _clean_json_response(response.text)
        overall_in = synthesis.get("overall")
        if not isinstance(overall_in, dict):
            raise ValueError("synthesis response is missing overall")
        overall_summary = str(overall_in.get("summary") or "").strip()
        if not overall_summary:
            raise ValueError("synthesis response is missing overall.summary")
        narrative_by_phase = {
            str(item.get("phase")): str(item.get("summary") or "").strip()
            for item in synthesis.get("phase_summary", [])
            if isinstance(item, dict) and item.get("phase")
        }
        for row in phase_rows:
            row["summary"] = narrative_by_phase.get(row["phase"], row["summary"])

        score_by_index = {int(pq["index"]): float(pq["score"]) for pq in assessed}
        evidence = synthesis.get("skill_evidence") or {}
        radar: dict[str, float | None] = {}
        for dimension in _SKILL_DIMENSIONS:
            raw_indexes = (
                evidence.get(dimension, []) if isinstance(evidence, dict) else []
            )
            dimension_scores: list[float] = []
            seen: set[int] = set()
            if isinstance(raw_indexes, list):
                for raw_index in raw_indexes:
                    try:
                        index = int(raw_index)
                    except (TypeError, ValueError):
                        continue
                    if index not in seen and index in score_by_index:
                        seen.add(index)
                        dimension_scores.append(score_by_index[index])
            radar[dimension] = (
                round(sum(dimension_scores) / len(dimension_scores), 1)
                if dimension_scores
                else None
            )

        growth = overall_in.get("key_growth_areas")
        growth = growth if isinstance(growth, list) else []
        return {
            "overall": {
                "score": overall_score,
                "summary": overall_summary,
                "strengths": _string_list(overall_in.get("strengths"), limit=5),
                "weaknesses": _string_list(overall_in.get("weaknesses"), limit=5),
                "key_growth_areas": [item for item in growth if isinstance(item, dict)][
                    :4
                ],
            },
            "phase_summary": phase_rows,
            "per_question": per_question_results,
            "skill_radar": radar,
            "tag": str(synthesis.get("tag") or "").strip()[:8],
        }
    except Exception as exc:
        logger.error("Report synthesis failed: %s", exc)
        return {
            "overall": {
                "score": overall_score,
                "summary": "综合叙述生成失败，逐题分析和代码聚合分数仍可正常查看。",
                "strengths": [],
                "weaknesses": [],
                "key_growth_areas": [],
            },
            "phase_summary": phase_rows,
            "per_question": per_question_results,
            "skill_radar": empty_radar,
            "tag": "",
        }


def _string_list(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()][:limit]


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
    """Extract Q&A when needed, then use the shared batch analysis path."""
    if qa_pairs is None:
        qa_pairs = await extract_qa_pairs_with_llm(
            transcript, resume_context, user_id=user_id
        )
    return await analyze_qa_batched(
        qa_pairs,
        resume_context=resume_context,
        jd_context=jd_context,
        on_progress=on_progress,
        user_id=user_id,
    )


def _render_qa_block(qa: dict[str, Any], label: str) -> str:
    topic = qa.get("question_summary") or qa.get("topic") or ""
    topic_str = f", topic={topic}" if topic else ""
    return (
        f"{label} [index={qa['index']}, phase={qa.get('phase', 'general')}{topic_str}]\n"
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

    prompt = QUESTION_ANALYSIS_PROMPT.format(
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
        by_index = await _request_batch_result(
            llm, prompt, [int(q["index"]) for q in batch]
        )
        out = []
        for q in batch:
            item = by_index[int(q["index"])]
            out.append(
                {
                    "index": q["index"],
                    "phase": q.get("phase", "general"),
                    "question": q["question"],
                    "answer": q["answer"],
                    **item,
                }
            )
        return out
    except Exception as exc:  # noqa: BLE001
        logger.error("Question-analysis batch failed after retries: %s", exc)
        return _fallback()


async def analyze_qa_batched(
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
    """Score structured Q&A in batches and synthesize one report for any source."""
    normalized: list[dict[str, Any]] = []
    for i, pair in enumerate(qa_pairs, start=1):
        if not isinstance(pair, dict):
            continue
        normalized.append(
            {
                "index": i,
                "phase": pair.get("phase") or "general",
                "question": str(pair.get("question") or ""),
                "answer": str(pair.get("answer") or ""),
                "is_follow_up": bool(pair.get("is_follow_up", False)),
                "topic": pair.get("topic"),
                "question_summary": pair.get("question_summary"),
            }
        )

    if not normalized:
        return await _synthesize_report([], resume_context, jd_context, llm=None)

    # Owner's primary model drives scoring + synthesis (MDL-1).
    analysis_llm = get_llm_for_role("primary", user_id=user_id)
    semaphore = asyncio.Semaphore(_ANALYSIS_MAX_CONCURRENCY)
    batch_size = max(1, int(batch_size))

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
        prev_window = normalized[max(0, start - ctx_prev) : start]
        next_window = normalized[end : end + ctx_next]
        tasks.append(asyncio.create_task(_run_batch(batch, prev_window, next_window)))

    batched_results = await asyncio.gather(*tasks)
    per_question_results: list[dict[str, Any]] = [
        r for chunk in batched_results for r in chunk
    ]

    logger.info(
        "Question analysis complete: %d questions across %d batches (size=%d, prev=%d, next=%d)",
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


__all__ = ["analyze_interview", "analyze_qa_batched", "extract_qa_pairs_with_llm"]
