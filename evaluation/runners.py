"""Shared async runners for the three evaluation layers.

Both the CLI (``eval_runner.py``) and the pytest suite (``test_*.py``)
call into these. The contract is simple: input = a list of golden-
dataset rows, output = a metric dict. Side effects (printing, report
writing) live in the caller.

Layer mapping:
  L1 retrieval — ``run_retrieval``  : hybrid Milvus + BM25 + reranker;
                                     no LLM cost.
  L2 generation — ``run_generation``: retrieve → DeepSeek answer →
                                     RAGAS v0.4.3 scores. LLM-heavy.
  L3 planner   — ``run_trajectory`` : query → plan_query →
                                     routing-decision aggregates.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

from evaluation.metrics import (
    aggregate_scores,
    chunk_relevance,
    hit_at_k,
    ndcg_at_k,
    overlap_score,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)

logger = logging.getLogger(__name__)

GOLDEN_DATASET_PATH = Path(__file__).with_name("golden_dataset.jsonl")
DEFAULT_USER = "eval_user_a"

# QPS throttle between LLM calls — prevents vendor rate-limit storms when
# running L2 / L3 over the full 835-row dataset. Tuned for DeepSeek's
# free tier; bump down on a paid account.
_LLM_THROTTLE_SECONDS = 0.6
_RAGAS_THROTTLE_SECONDS = 0.3


# ── Dataset loading ────────────────────────────────────────────────────


def load_dataset(limit: int | None = None) -> list[dict[str, Any]]:
    """Load every row from ``golden_dataset.jsonl``."""
    if not GOLDEN_DATASET_PATH.exists():
        raise FileNotFoundError(f"Golden dataset missing: {GOLDEN_DATASET_PATH}")
    rows: list[dict[str, Any]] = []
    with GOLDEN_DATASET_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows[:limit] if limit else rows


def filter_by_layer(
    rows: list[dict[str, Any]],
    layer: str,
) -> list[dict[str, Any]]:
    """Filter rows whose ``layer`` field is ``layer`` or ``"all"``."""
    return [r for r in rows if r.get("layer") in (layer, "all")]


# ── L1 retrieval ───────────────────────────────────────────────────────


async def run_retrieval(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate retrieval quality across ``rows``.

    Calls the production ``query_knowledge_base`` once per row and
    derives Hit / Precision / Recall / MRR / nDCG against the
    ``reference_answer`` (or the query itself when no reference).

    No LLM cost — runs purely against Milvus + BM25 + the reranker.
    """
    from app.rag.retriever import init_reranker, query_knowledge_base

    init_reranker()
    if not rows:
        return {"samples": 0, "error": "No rows."}

    hits: list[int] = []
    precisions: list[float] = []
    recalls: list[float] = []
    mrrs: list[float] = []
    ndcgs: list[float] = []
    latencies: list[float] = []
    isolation_violations = 0

    for idx, row in enumerate(rows, 1):
        user_id = row.get("user_id", DEFAULT_USER)
        start = time.perf_counter()
        result = await query_knowledge_base(
            query_str=row["query"],
            user_id=user_id,
            source_type=row.get("source_type"),
        )
        latency_ms = (time.perf_counter() - start) * 1000
        latencies.append(latency_ms)

        chunks = result.get("chunks", [])
        ref = row.get("reference_answer", row["query"])
        flags = [chunk_relevance(ref, c.get("text", "")) for c in chunks]

        hits.append(hit_at_k(flags, k=3))
        precisions.append(precision_at_k(flags, k=3))
        recalls.append(recall_at_k(flags, k=3))
        mrrs.append(reciprocal_rank(flags[:5]))
        scores = [overlap_score(ref, c.get("text", "")) for c in chunks[:5]]
        ndcgs.append(ndcg_at_k(scores, k=5))

        # Multi-tenant leakage check — any chunk tagged with a different
        # user_id than the requester is a hard isolation failure.
        for c in chunks:
            c_user = c.get("metadata", {}).get("user_id")
            if c_user and c_user != user_id:
                isolation_violations += 1

        logger.info(
            "[L1 %d/%d] hit=%d p@3=%.2f latency=%.0fms",
            idx, len(rows), hits[-1], precisions[-1], latency_ms,
        )

    n = len(rows)
    return {
        "samples": n,
        "hit_at_3": round(sum(hits) / n, 4),
        "precision_at_3": round(sum(precisions) / n, 4),
        "recall_at_3": round(sum(recalls) / n, 4),
        "mrr_at_5": round(sum(mrrs) / n, 4),
        "ndcg_at_5": round(sum(ndcgs) / n, 4),
        "latency_ms": aggregate_scores(latencies),
        "isolation_violations": isolation_violations,
    }


# ── L2 generation ──────────────────────────────────────────────────────


async def run_generation(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """End-to-end RAG quality: retrieve → DeepSeek answer → RAGAS scores.

    Pulls per-row context via the same ``knowledge_retriever`` the
    production engine uses, then has DeepSeek answer the question
    grounded in those chunks. RAGAS v0.4.3 scores each (query, answer,
    context, reference) tuple on four axes:

      - Faithfulness                  — does the answer stay grounded?
      - ContextPrecisionWithReference — are the retrieved chunks
                                        relevant to the reference?
      - ContextRecall                 — does the reference get covered?
      - FactualCorrectness            — is the answer factually right?

    Plus two cheap counters: ``hallucination_gate_rate`` (how often
    retrieval came back empty so the engine should refuse to answer)
    and ``empty_answer_rate``.
    """
    from app.rag.knowledge_retriever import knowledge_retriever
    from app.rag.retriever import init_reranker
    from evaluation.llm_factory import build_deepseek_llm

    init_reranker()
    if not rows:
        return {"samples": 0, "error": "No rows."}

    llm = build_deepseek_llm()
    scored_data: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []
    ttfb_list: list[float] = []
    e2e_list: list[float] = []
    retrieval_latencies: list[float] = []

    for idx, row in enumerate(rows, 1):
        user_id = row.get("user_id", DEFAULT_USER)

        # ── Retrieval ──
        t_start = time.perf_counter()
        kr = await knowledge_retriever.retrieve(
            dense_query=row["query"],
            sparse_query=row["query"],
            user_id=user_id,
            source_type=row.get("source_type"),
        )
        retrieval_ms = (time.perf_counter() - t_start) * 1000
        retrieval_latencies.append(retrieval_ms)

        contexts = [c.get("text", "") for c in kr.chunks[:5]]
        context_block = "\n\n".join(contexts)

        prompt = (
            "你是面试问答助手。请严格基于给定参考资料回答问题；"
            "如果资料不足，明确说资料不足，不要编造。\n\n"
            f"问题：{row['query']}\n\n"
            f"参考资料：\n{context_block}"
        )

        # ── Generation (stream so we can record TTFB) ──
        answer, ttfb_ms = await _stream_with_ttfb(llm, prompt)
        e2e_ms = (time.perf_counter() - t_start) * 1000
        ttfb_total_ms = retrieval_ms + ttfb_ms
        ttfb_list.append(ttfb_total_ms)
        e2e_list.append(e2e_ms)

        scored_data.append({
            "user_input": row["query"],
            "response": answer,
            "retrieved_contexts": contexts,
            "reference": row.get("reference_answer", ""),
        })
        details.append({
            "id": row.get("id", ""),
            "retrieval_hit": kr.retrieval_hit,
            "empty_answer": not answer.strip(),
            "retrieval_ms": round(retrieval_ms, 1),
            "ttfb_ms": round(ttfb_total_ms, 1),
            "e2e_ms": round(e2e_ms, 1),
        })
        logger.info(
            "[L2 %d/%d] %d chars | ret=%.0fms ttfb=%.0fms e2e=%.0fms",
            idx, len(rows), len(answer), retrieval_ms, ttfb_total_ms, e2e_ms,
        )

        await asyncio.sleep(_LLM_THROTTLE_SECONDS)

    ragas_scores = await _score_with_ragas(scored_data)

    summary: dict[str, Any] = {"samples": len(rows)}
    summary.update(ragas_scores)
    summary["hallucination_gate_rate"] = round(
        sum(1 for d in details if not d["retrieval_hit"]) / len(details), 4,
    )
    summary["empty_answer_rate"] = round(
        sum(1 for d in details if d["empty_answer"]) / len(details), 4,
    )
    summary["retrieval_latency_ms"] = aggregate_scores(retrieval_latencies)
    summary["ttfb_ms"] = aggregate_scores(ttfb_list)
    summary["e2e_latency_ms"] = aggregate_scores(e2e_list)
    summary["per_sample_details"] = details
    return summary


async def _stream_with_ttfb(llm, prompt: str) -> tuple[str, float]:
    """Stream ``prompt`` through ``llm``, returning (full_text, ttfb_ms).

    Falls back to a non-streaming call if the stream errors mid-flight
    (rare; DeepSeek occasionally drops connections).
    """
    t_start = time.perf_counter()
    ttfb_ms = 0.0
    ttfb_recorded = False
    parts: list[str] = []
    try:
        async for chunk in llm.astream(prompt):
            if not ttfb_recorded:
                ttfb_ms = (time.perf_counter() - t_start) * 1000
                ttfb_recorded = True
            content = chunk.content if hasattr(chunk, "content") else str(chunk)
            if content:
                parts.append(content)
    except Exception as exc:
        logger.warning("L2 stream failed, retrying non-stream: %s", exc)
        response = await llm.ainvoke(prompt)
        text = response.content if isinstance(response.content, str) else str(response.content)
        parts = [text]
        ttfb_ms = (time.perf_counter() - t_start) * 1000
    return "".join(parts), ttfb_ms


async def _score_with_ragas(scored_data: list[dict[str, Any]]) -> dict[str, Any]:
    """Score every ``scored_data`` item with the four RAGAS metrics.

    Returns ``{metric_name: mean_score}``. Failures on individual
    samples are logged and skipped — one flaky LLM response shouldn't
    blank the whole batch.
    """
    if not scored_data:
        return {}

    from evaluation.llm_factory import build_ragas_llm
    from ragas.metrics.collections import (
        ContextPrecisionWithReference,
        ContextRecall,
        FactualCorrectness,
        Faithfulness,
    )

    ragas_llm = build_ragas_llm()
    metric_objs = [
        Faithfulness(llm=ragas_llm),
        ContextPrecisionWithReference(llm=ragas_llm),
        ContextRecall(llm=ragas_llm),
        FactualCorrectness(llm=ragas_llm),
    ]
    metric_keys = [
        "faithfulness",
        "context_precision_with_reference",
        "context_recall",
        "factual_correctness",
    ]
    collected: dict[str, list[float]] = {k: [] for k in metric_keys}

    for s_idx, item in enumerate(scored_data, 1):
        for metric, key in zip(metric_objs, metric_keys):
            try:
                result_obj = await metric.ascore(**_ragas_kwargs(metric, item))
                value = (
                    result_obj.value if hasattr(result_obj, "value")
                    else float(result_obj)
                )
                if value is not None and value == value:  # not NaN
                    collected[key].append(float(value))
            except Exception as exc:
                logger.warning(
                    "[RAGAS %d/%d] %s error: %s",
                    s_idx, len(scored_data), key, exc,
                )
            await asyncio.sleep(_RAGAS_THROTTLE_SECONDS)

    return {
        key: round(sum(values) / len(values), 4) if values else None
        for key, values in collected.items()
    }


def _ragas_kwargs(metric, item: dict[str, Any]) -> dict[str, Any]:
    """Per-metric kwargs RAGAS v0.4.3 expects.

    RAGAS v0.4.3's ``ascore()`` signature varies by metric class; this
    routes the right subset of (user_input / response / retrieved_contexts
    / reference) to each one rather than dumping the full quad.
    """
    from ragas.metrics.collections import (
        ContextPrecisionWithReference,
        ContextRecall,
        FactualCorrectness,
        Faithfulness,
    )

    if isinstance(metric, Faithfulness):
        return {
            "user_input": item["user_input"],
            "response": item["response"],
            "retrieved_contexts": item["retrieved_contexts"],
        }
    if isinstance(metric, ContextPrecisionWithReference):
        return {
            "user_input": item["user_input"],
            "reference": item["reference"],
            "retrieved_contexts": item["retrieved_contexts"],
        }
    if isinstance(metric, ContextRecall):
        return {
            "user_input": item["user_input"],
            "retrieved_contexts": item["retrieved_contexts"],
            "reference": item["reference"],
        }
    if isinstance(metric, FactualCorrectness):
        return {
            "response": item["response"],
            "reference": item["reference"],
        }
    return {
        "user_input": item["user_input"],
        "response": item["response"],
        "retrieved_contexts": item["retrieved_contexts"],
    }


# ── L3 planner routing ─────────────────────────────────────────────────


async def run_trajectory(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate planner routing decisions across ``rows``.

    Calls ``app.conversation.query_planner.plan_query`` once per row
    (with an empty session_state / recent_turns / memory descriptions
    so each query is judged in isolation). Then reports:

      - ``knowledge_retrieval_trigger_rate`` — fraction of queries the
        planner decided needed RAG. Since the bundled golden dataset
        is 100% QA-tagged, healthy planners should be ≥ 0.80.
      - ``dense_query_populated_rate`` — sanity check that when RAG is
        on, the planner actually produces a non-empty dense_query
        string (an empty one would short-circuit retrieval upstream).
      - ``plan_call_failures`` — how many rows raised inside
        ``plan_query`` (rare, but tracked).

    The legacy ``expected_plan`` field comparison from pre-P8 is gone —
    the new ``QueryPlan`` shape (post-planner-merge) dropped
    ``answer_mode`` / ``knowledge_sources`` / ``standalone_query``, and
    the dataset never had ``expected_plan`` rows anyway. We measure
    aggregate behaviour, not per-row equality.
    """
    from app.conversation.query_planner import plan_query

    if not rows:
        return {"samples": 0, "error": "No rows."}

    knowledge_triggered = 0
    dense_query_non_empty = 0
    plan_call_failures = 0

    for idx, row in enumerate(rows, 1):
        try:
            plan = await plan_query(
                user_message=row["query"],
                session_state={},
                recent_turns=[],
                knowledge_index_lines=[],
                strategy_description="",
                habit_description="",
                global_memory_on=True,
            )
        except Exception as exc:
            plan_call_failures += 1
            logger.warning("[L3 %d/%d] plan_query failed: %s", idx, len(rows), exc)
            await asyncio.sleep(_LLM_THROTTLE_SECONDS)
            continue

        if plan.needs_knowledge_retrieval:
            knowledge_triggered += 1
        if plan.dense_query.strip():
            dense_query_non_empty += 1

        logger.info(
            "[L3 %d/%d] needs_knowledge=%s dense_query=%r",
            idx, len(rows), plan.needs_knowledge_retrieval,
            plan.dense_query[:40],
        )
        await asyncio.sleep(_LLM_THROTTLE_SECONDS)

    succeeded = len(rows) - plan_call_failures
    return {
        "samples": len(rows),
        "succeeded": succeeded,
        "plan_call_failures": plan_call_failures,
        "knowledge_triggered": knowledge_triggered,
        "knowledge_retrieval_trigger_rate": (
            round(knowledge_triggered / succeeded, 4) if succeeded else None
        ),
        "dense_query_populated_rate": (
            round(dense_query_non_empty / succeeded, 4) if succeeded else None
        ),
    }


# ── Bootstrap helper shared by CLI + pytest ────────────────────────────


def prepare_runtime() -> None:
    """One-time runtime bootstrap.

    Called by both the CLI and the pytest session fixture so the
    evaluation environment matches what the production backend sees:

      1. ``prepare_hf_runtime`` — set HF_HOME, clear dead proxy env,
         create cache dirs.
      2. ``init_rag_settings``  — register the LlamaIndex embedding
         model + primary LLM so ``query_knowledge_base`` and
         ``plan_query`` can resolve them.
      3. ``init_reranker``      — load BGE (or the remote reranker
         provider) into the singleton.

    Idempotent — safe to call from every test session and the CLI.
    """
    from app.core.hf_runtime import prepare_hf_runtime
    from app.rag.embeddings import init_rag_settings
    from app.rag.retriever import init_reranker

    prepare_hf_runtime()
    init_rag_settings()
    init_reranker()
