"""Scoring and synthesis for already-grounded interview QA.

Upload recordings are structured by transcript_structure_service from immutable
word evidence. Mock interviews arrive as ConversationMessage-derived QA. This
module intentionally owns neither ASR nor QA extraction.
"""

import asyncio
import json
import logging
import math
from typing import Any, Callable

from llama_index.core.llms import LLM

from app.core.llm_client_factory import get_llm_for_role
from app.prompts.voice_analysis import QUESTION_ANALYSIS_PROMPT, SYNTHESIS_PROMPT

logger = logging.getLogger(__name__)

_ANALYSIS_MAX_ATTEMPTS = 2
_ANALYSIS_RETRY_BASE_S = 2.0
_ANALYSIS_MAX_CONCURRENCY = 5
_ANALYSIS_RECOVERY_DELAY_S = 0.25
_SYNTHESIS_MAX_ATTEMPTS = 2
_SYNTHESIS_RETRY_BASE_S = 2.0
_SKILL_DIMENSIONS = ("系统设计", "编码能力", "基础知识", "沟通表达", "项目经验")


def _notify_progress(on_progress, n: int) -> None:
    """Best-effort progress ping; scoring must survive a failed progress write."""
    if on_progress is None:
        return
    try:
        on_progress(n)
    except Exception:  # noqa: BLE001
        logger.warning("on_progress callback failed", exc_info=True)


def _clean_json_response(raw_text: str) -> dict[str, Any]:
    raw_text = str(raw_text).strip()
    if raw_text.startswith("```json"):
        raw_text = raw_text[7:]
    elif raw_text.startswith("```"):
        raw_text = raw_text[3:]
    if raw_text.endswith("```"):
        raw_text = raw_text[:-3]
    return json.loads(raw_text.strip())


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


async def _request_synthesis_payload(llm: LLM, prompt: str) -> dict[str, Any]:
    """Retry transient transport and structured-output failures.

    A one-off malformed JSON response used to permanently mark an otherwise
    successful interview as ``completed`` with an empty narrative.  Repeating
    the exact prompt is safe: synthesis is read-only and persistence happens
    only after this function returns a validated object.
    """

    last_exc: Exception | None = None
    for attempt in range(1, _SYNTHESIS_MAX_ATTEMPTS + 1):
        try:
            response = await llm.acomplete(
                prompt,
                response_format={"type": "json_object"},
            )
            payload = _clean_json_response(response.text)
            overall = payload.get("overall")
            if not isinstance(overall, dict):
                raise ValueError("synthesis response is missing overall")
            if not str(overall.get("summary") or "").strip():
                raise ValueError("synthesis response is missing overall.summary")
            return payload
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.warning(
                "Report-synthesis attempt %d/%d failed: %s",
                attempt,
                _SYNTHESIS_MAX_ATTEMPTS,
                exc,
            )
            if attempt < _SYNTHESIS_MAX_ATTEMPTS:
                await asyncio.sleep(_SYNTHESIS_RETRY_BASE_S * attempt)
    assert last_exc is not None
    raise last_exc


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
            "generation_status": "failed",
            "generation_warnings": [message],
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
        synthesis = await _request_synthesis_payload(llm, prompt)
        overall_in = synthesis.get("overall")
        assert isinstance(overall_in, dict)
        overall_summary = str(overall_in.get("summary") or "").strip()
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
        warnings = (
            [f"{failed_count} 题逐题分析失败，未计入总分。"] if failed_count else []
        )
        return {
            "generation_status": "partial" if warnings else "complete",
            "generation_warnings": warnings,
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
        deterministic = _deterministic_report_fallback(
            per_question_results,
            assessed=assessed,
            overall_score=overall_score,
            phase_rows=phase_rows,
            failed_count=failed_count,
        )
        return {
            "generation_status": "partial",
            "generation_warnings": [
                "模型综合叙述生成失败；当前展示由逐题评分确定性汇总的报告，可稍后重新生成模型综述。"
            ],
            "overall": deterministic["overall"],
            "phase_summary": phase_rows,
            "per_question": per_question_results,
            "skill_radar": deterministic["skill_radar"],
            "tag": "",
        }


def _deterministic_report_fallback(
    per_question_results: list[dict[str, Any]],
    *,
    assessed: list[dict[str, Any]],
    overall_score: float | None,
    phase_rows: list[dict[str, Any]],
    failed_count: int,
) -> dict[str, Any]:
    """Build a useful, auditable report when narrative synthesis is unavailable."""

    strongest = sorted(
        assessed,
        key=lambda item: float(item.get("score") or 0),
        reverse=True,
    )[:3]
    weakest = sorted(
        assessed,
        key=lambda item: float(item.get("score") or 0),
    )[:3]

    def _evidence_line(item: dict[str, Any]) -> str:
        question = " ".join(str(item.get("question") or "").split())
        critique = " ".join(str(item.get("critique") or "").split())
        prefix = f"第{item.get('index')}题（{question[:36]}）"
        return f"{prefix}：{critique[:100]}" if critique else prefix

    strengths = [
        _evidence_line(item)
        for item in strongest
        if isinstance(item.get("score"), (int, float)) and float(item["score"]) >= 6
    ]
    weaknesses = [
        _evidence_line(item)
        for item in weakest
        if isinstance(item.get("score"), (int, float)) and float(item["score"]) <= 6
    ]

    summary = (
        f"本次共识别 {len(per_question_results)} 个问答，其中 {len(assessed)} 题形成有效评分"
        f"，综合得分为 {overall_score if overall_score is not None else '未评分'}/10。"
    )
    if failed_count:
        summary += f"另有 {failed_count} 题因模型返回异常未计入总分。"
    if strengths:
        summary += f" 相对表现较好的是{strengths[0].split('：', 1)[0]}。"
    if weaknesses:
        summary += f" 优先改进{weaknesses[0].split('：', 1)[0]}的回答完整性与证据。"

    radar_evidence: dict[str, list[float]] = {
        dimension: [] for dimension in _SKILL_DIMENSIONS
    }
    system_terms = (
        "系统",
        "架构",
        "工作流",
        "agent",
        "langgraph",
        "rag",
        "降级",
        "上下文",
        "记忆",
    )
    coding_terms = ("编码", "代码", "python", "java", "go", "算法", "数据结构", "api")
    project_terms = ("项目", "实习", "落地", "工程", "部署", "实践")
    for item in assessed:
        score = float(item["score"])
        phase = str(item.get("phase") or "general")
        evidence_text = " ".join(
            [
                str(item.get("question") or ""),
                *[str(tag) for tag in item.get("tags", [])],
            ]
        ).lower()
        if phase == "technical":
            radar_evidence["基础知识"].append(score)
        if phase in {"self_intro", "behavioral", "reverse_qa", "general"}:
            radar_evidence["沟通表达"].append(score)
        if phase == "resume_deep_dive" or any(
            term in evidence_text for term in project_terms
        ):
            radar_evidence["项目经验"].append(score)
        if any(term in evidence_text for term in system_terms):
            radar_evidence["系统设计"].append(score)
        if any(term in evidence_text for term in coding_terms):
            radar_evidence["编码能力"].append(score)

    radar = {
        dimension: round(sum(scores) / len(scores), 1) if scores else None
        for dimension, scores in radar_evidence.items()
    }
    growth_areas = (
        [
            {
                "area": "回答完整性与证据",
                "advice": "优先复盘低分题，补齐结论、依据、个人行动和可验证结果。",
            }
        ]
        if weaknesses
        else []
    )
    return {
        "overall": {
            "score": overall_score,
            "summary": summary,
            "strengths": strengths,
            "weaknesses": weaknesses,
            "key_growth_areas": growth_areas,
        },
        "phase_summary": phase_rows,
        "skill_radar": radar,
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
    """Analyze QA whose source structure has already been verified.

    The transcript argument remains in the compatibility signature for callers
    that also display it, but raw text can no longer trigger extraction.
    """
    del transcript
    if qa_pairs is None:
        raise ValueError(
            "qa_pairs are required; uploaded audio must pass the v2 transcript "
            "evidence pipeline before scoring"
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


async def _recover_failed_questions(
    per_question_results: list[dict[str, Any]],
    normalized: list[dict[str, Any]],
    *,
    resume_context: str,
    jd_context: str,
    llm: LLM,
    ctx_prev: int,
    ctx_next: int,
) -> list[dict[str, Any]]:
    """Retry failed batch members one-by-one after the concurrent wave.

    Some OpenAI-compatible providers respond with an empty body under a short
    burst even though the same request succeeds immediately when serialized.
    Retrying the original batch alone left a large interview permanently
    partial. This recovery pass is bounded by the number of failed questions
    and keeps real failures explicitly unscored.
    """

    by_index = {int(item["index"]): item for item in normalized}
    position_by_index = {
        int(item["index"]): position for position, item in enumerate(normalized)
    }
    recovered: dict[int, dict[str, Any]] = {}
    failed_indexes = [
        int(item["index"])
        for item in per_question_results
        if item.get("analysis_failed") is True
    ]
    for recovery_position, index in enumerate(failed_indexes):
        item = by_index.get(index)
        position = position_by_index.get(index)
        if item is None or position is None:
            continue
        if recovery_position:
            await asyncio.sleep(_ANALYSIS_RECOVERY_DELAY_S)
        retry = await _analyze_batch(
            [item],
            normalized[max(0, position - ctx_prev) : position],
            normalized[position + 1 : position + 1 + ctx_next],
            resume_context=resume_context,
            jd_context=jd_context,
            llm=llm,
        )
        if retry and retry[0].get("analysis_failed") is not True:
            recovered[index] = retry[0]

    if recovered:
        logger.info(
            "Recovered %d/%d failed question analyses with serialized retries.",
            len(recovered),
            len(failed_indexes),
        )
    return [recovered.get(int(item["index"]), item) for item in per_question_results]


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
    per_question_results = await _recover_failed_questions(
        per_question_results,
        normalized,
        resume_context=resume_context,
        jd_context=jd_context,
        llm=analysis_llm,
        ctx_prev=ctx_prev,
        ctx_next=ctx_next,
    )

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


__all__ = ["analyze_interview", "analyze_qa_batched"]
