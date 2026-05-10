"""CLI entry point for the RAG evaluation suite.

Usage::

    # Run all three layers
    python -m evaluation.eval_runner --all

    # Run a specific layer
    python -m evaluation.eval_runner --layer retrieval
    python -m evaluation.eval_runner --layer generation
    python -m evaluation.eval_runner --layer trajectory

    # Limit samples and generate report
    python -m evaluation.eval_runner --layer retrieval --limit 10 --report

    # Show help
    python -m evaluation.eval_runner --help
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

# Fix Windows console encoding
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# Bootstrap backend imports
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.hf_runtime import prepare_hf_runtime
from app.core.config import settings

GOLDEN_DATASET_PATH = Path(__file__).with_name("golden_dataset.jsonl")


def _load_dataset(limit: int | None = None) -> list[dict[str, Any]]:
    if not GOLDEN_DATASET_PATH.exists():
        print(f"ERROR: Golden dataset not found: {GOLDEN_DATASET_PATH}")
        sys.exit(1)
    rows: list[dict[str, Any]] = []
    with GOLDEN_DATASET_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    if limit:
        rows = rows[:limit]
    return rows


# ---------------------------------------------------------------------------
# Layer runners
# ---------------------------------------------------------------------------

async def run_retrieval(dataset: list[dict[str, Any]]) -> dict[str, Any]:
    from app.rag.retriever import query_knowledge_base, init_reranker
    from evaluation.metrics import (
        chunk_relevance, hit_at_k, precision_at_k, recall_at_k,
        reciprocal_rank, ndcg_at_k, overlap_score, aggregate_scores,
    )

    init_reranker()
    rows = [r for r in dataset if r.get("layer") in ("retrieval", "all")]
    if not rows:
        return {"error": "No retrieval-layer rows found."}

    hits: list[int] = []
    precisions: list[float] = []
    recalls: list[float] = []
    mrrs: list[float] = []
    ndcgs: list[float] = []
    latencies: list[float] = []
    isolation_violations = 0

    for idx, row in enumerate(rows, 1):
        user_id = row.get("user_id", "eval_user_a")
        start = time.perf_counter()
        result = await query_knowledge_base(
            query_str=row["query"],
            user_id=user_id,
            source_type=row.get("source_type"),
        )
        elapsed = (time.perf_counter() - start) * 1000
        latencies.append(elapsed)

        chunks = result.get("chunks", [])
        ref = row.get("reference_answer", row["query"])
        flags = [chunk_relevance(ref, c.get("text", "")) for c in chunks]

        hits.append(hit_at_k(flags, k=3))
        precisions.append(precision_at_k(flags, k=3))
        recalls.append(recall_at_k(flags, k=3))
        mrrs.append(reciprocal_rank(flags[:5]))
        scores = [overlap_score(ref, c.get("text", "")) for c in chunks[:5]]
        ndcgs.append(ndcg_at_k(scores, k=5))

        # Multi-tenant check
        for c in chunks:
            c_user = c.get("metadata", {}).get("user_id")
            if c_user and c_user != user_id:
                isolation_violations += 1

        print(f"  [{idx}/{len(rows)}] hit={hits[-1]} p@3={precisions[-1]:.2f} latency={elapsed:.0f}ms")

    n = len(rows)
    return {
        "samples": n,
        "hit_at_3": round(sum(hits) / n, 4),
        "precision_at_3": round(sum(precisions) / n, 4),
        "recall_at_3": round(sum(recalls) / n, 4),
        "mrr_at_5": round(sum(mrrs) / n, 4),
        "ndcg_at_5": round(sum(ndcgs) / n, 4),
        "latency": aggregate_scores(latencies),
        "isolation_violations": isolation_violations,
    }


async def run_generation(dataset: list[dict[str, Any]]) -> dict[str, Any]:
    from app.rag.retriever import query_knowledge_base, init_reranker
    from evaluation.llm_factory import build_deepseek_llm, build_ragas_llm

    from ragas.metrics.collections import (
        ContextPrecisionWithReference,
        ContextRecall,
        Faithfulness,
        FactualCorrectness,
    )

    init_reranker()

    rows = [r for r in dataset if r.get("layer") in ("generation", "all")]
    if not rows:
        return {"error": "No generation-layer rows found."}

    llm = build_deepseek_llm()
    # Store data for RAGAS scoring (plain dicts, not Sample objects)
    scored_data: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []
    ttfb_list: list[float] = []
    e2e_list: list[float] = []
    retrieval_latencies: list[float] = []

    for idx, row in enumerate(rows, 1):
        user_id = row.get("user_id", "eval_user_a")

        # ── Measure retrieval latency ──
        t_start = time.perf_counter()
        result = await query_knowledge_base(
            query_str=row["query"],
            user_id=user_id,
            source_type=row.get("source_type"),
        )
        t_retrieved = time.perf_counter()
        retrieval_ms = (t_retrieved - t_start) * 1000
        retrieval_latencies.append(retrieval_ms)

        chunks = result.get("chunks", [])
        contexts = [c.get("text", "") for c in chunks[:5]]
        context_block = "\n\n".join(contexts)

        prompt = (
            "你是面试问答助手。请严格基于给定参考资料回答问题；"
            "如果资料不足，明确说资料不足，不要编造。\n\n"
            f"问题：{row['query']}\n\n"
            f"参考资料：\n{context_block}"
        )

        # ── Measure TTFB (time to first token) via streaming ──
        t_gen_start = time.perf_counter()
        ttfb_recorded = False
        ttfb_ms = 0.0
        answer_chunks: list[str] = []

        try:
            async for chunk in llm.astream(prompt):
                if not ttfb_recorded:
                    ttfb_ms = (time.perf_counter() - t_gen_start) * 1000
                    ttfb_recorded = True
                content = chunk.content if hasattr(chunk, "content") else str(chunk)
                if content:
                    answer_chunks.append(content)
        except Exception as e:
            # Fallback to non-streaming if streaming fails
            response = await llm.ainvoke(prompt)
            answer_chunks = [response.content if isinstance(response.content, str) else str(response.content)]
            ttfb_ms = (time.perf_counter() - t_gen_start) * 1000

        t_done = time.perf_counter()
        answer = "".join(answer_chunks)

        # ── Record timings ──
        e2e_ms = (t_done - t_start) * 1000  # Full end-to-end: retrieval + generation
        ttfb_total_ms = retrieval_ms + ttfb_ms  # TTFB from user perspective: retrieval + first token
        ttfb_list.append(ttfb_total_ms)
        e2e_list.append(e2e_ms)

        retrieval_hit = not any(
            marker in result.get("answer", "")
            for marker in ["[SYSTEM_EMPTY_WARNING]"]
        )

        scored_data.append({
            "user_input": row["query"],
            "response": answer,
            "retrieved_contexts": contexts,
            "reference": row.get("reference_answer", ""),
        })
        details.append({
            "id": row.get("id", ""),
            "retrieval_hit": retrieval_hit,
            "empty_answer": not answer.strip(),
            "retrieval_ms": round(retrieval_ms, 1),
            "ttfb_ms": round(ttfb_total_ms, 1),
            "e2e_ms": round(e2e_ms, 1),
        })
        print(
            f"  [{idx}/{len(rows)}] {len(answer)} chars | "
            f"ret={retrieval_ms:.0f}ms ttfb={ttfb_total_ms:.0f}ms e2e={e2e_ms:.0f}ms"
        )

        # QPS throttle: 0.6s between LLM calls
        await asyncio.sleep(0.6)

    # RAGAS evaluation via ascore() with keyword arguments (v0.4.3 API)
    ragas_llm = build_ragas_llm()
    metrics = [
        Faithfulness(llm=ragas_llm),
        ContextPrecisionWithReference(llm=ragas_llm),
        ContextRecall(llm=ragas_llm),
        FactualCorrectness(llm=ragas_llm),
    ]

    from evaluation.metrics import aggregate_scores
    metric_names = ["faithfulness", "context_precision_with_reference", "context_recall", "factual_correctness"]
    all_scores: dict[str, list[float]] = {m: [] for m in metric_names}

    # RAGAS v0.4.3 — dispatch kwargs by class type (metric.name may vary)
    def _build_kwargs(metric, item: dict) -> dict:
        if isinstance(metric, Faithfulness):
            return {"user_input": item["user_input"], "response": item["response"], "retrieved_contexts": item["retrieved_contexts"]}
        elif isinstance(metric, ContextRecall):
            return {"user_input": item["user_input"], "retrieved_contexts": item["retrieved_contexts"], "reference": item["reference"]}
        elif isinstance(metric, FactualCorrectness):
            return {"response": item["response"], "reference": item["reference"]}
        elif isinstance(metric, ContextPrecisionWithReference):
            return {"user_input": item["user_input"], "reference": item["reference"], "retrieved_contexts": item["retrieved_contexts"]}
        else:
            # Generic fallback
            return {"user_input": item["user_input"], "response": item["response"], "retrieved_contexts": item["retrieved_contexts"]}

    for s_idx, item in enumerate(scored_data, 1):
        scored_any = False
        for metric in metrics:
            try:
                kwargs = _build_kwargs(metric, item)
                result_obj = await metric.ascore(**kwargs)
                metric_key = metric.name
                # MetricResult has .value attribute
                score_val = result_obj.value if hasattr(result_obj, "value") else float(result_obj)
                if metric_key in all_scores and score_val is not None and score_val == score_val:
                    all_scores[metric_key].append(float(score_val))
                    scored_any = True
            except Exception as e:
                print(f"  [RAGAS {s_idx}/{len(scored_data)}] {metric.name} error: {e}")
            await asyncio.sleep(0.3)
        if scored_any:
            print(f"  [RAGAS {s_idx}/{len(scored_data)}] scored")
        await asyncio.sleep(0.3)

    # Aggregate
    summary: dict[str, Any] = {"samples": len(rows)}
    for metric_name in metric_names:
        values = all_scores.get(metric_name, [])
        summary[metric_name] = round(sum(values) / len(values), 4) if values else None

    summary["hallucination_gate_rate"] = round(
        sum(1 for d in details if not d["retrieval_hit"]) / len(details), 4
    )
    summary["empty_answer_rate"] = round(
        sum(1 for d in details if d["empty_answer"]) / len(details), 4
    )

    # Latency metrics
    summary["retrieval_latency"] = aggregate_scores(retrieval_latencies)
    summary["ttfb"] = aggregate_scores(ttfb_list)
    summary["e2e_latency"] = aggregate_scores(e2e_list)
    summary["per_sample_details"] = details

    return summary


async def run_trajectory(dataset: list[dict[str, Any]]) -> dict[str, Any]:
    from app.agent.planner import plan_query

    rows = [r for r in dataset if r.get("layer") in ("trajectory", "all")]
    if not rows:
        return {"error": "No trajectory-layer rows found."}

    correct = 0
    total = 0

    for idx, row in enumerate(rows, 1):
        expected = row.get("expected_plan")
        if not expected:
            continue

        plan = await plan_query(user_message=row["query"], rewrite_context="")
        total += 1

        match = True
        for field, exp_val in expected.items():
            act_val = getattr(plan, field, None)
            if isinstance(exp_val, list):
                if not set(exp_val).issubset(set(act_val or [])):
                    match = False
            elif isinstance(exp_val, bool):
                if act_val != exp_val:
                    match = False
            elif isinstance(exp_val, str):
                if act_val != exp_val:
                    match = False

        if match:
            correct += 1
        status = "OK" if match else "MISMATCH"
        print(f"  [{idx}/{len(rows)}] {status} — {row['query'][:50]}")

    return {
        "samples": total,
        "routing_accuracy": round(correct / total, 4) if total else None,
        "correct": correct,
        "total": total,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Interview Copilot RAG Evaluation Suite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--all", action="store_true", help="Run all evaluation layers")
    parser.add_argument("--layer", choices=["retrieval", "generation", "trajectory"], help="Run a specific layer")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of dataset rows")
    parser.add_argument("--report", action="store_true", help="Generate Markdown + JSON report")
    args = parser.parse_args()

    if not args.all and not args.layer:
        parser.print_help()
        sys.exit(0)

    prepare_hf_runtime()

    # Initialize embedding model for retrieval
    from app.rag.embeddings import init_rag_settings
    init_rag_settings()

    dataset = _load_dataset(limit=args.limit)
    print(f"Loaded {len(dataset)} rows from golden dataset.\n")

    results: dict[str, dict[str, Any]] = {}

    layers_to_run = []
    if args.all:
        layers_to_run = ["retrieval", "generation", "trajectory"]
    elif args.layer:
        layers_to_run = [args.layer]

    for layer in layers_to_run:
        print(f"{'=' * 60}")
        print(f"  Layer: {layer.upper()}")
        print(f"{'=' * 60}")
        start = time.perf_counter()

        if layer == "retrieval":
            results["retrieval"] = asyncio.run(run_retrieval(dataset))
        elif layer == "generation":
            results["generation"] = asyncio.run(run_generation(dataset))
        elif layer == "trajectory":
            results["trajectory"] = asyncio.run(run_trajectory(dataset))

        elapsed = time.perf_counter() - start
        print(f"\n  Completed in {elapsed:.1f}s")
        print(json.dumps(results.get(layer, {}), ensure_ascii=False, indent=2))
        print()

    if args.report:
        from evaluation.report import generate_report

        report_dir = generate_report(
            retrieval=results.get("retrieval"),
            generation=results.get("generation"),
            trajectory=results.get("trajectory"),
        )
        print(f"Report saved to: {report_dir}")


if __name__ == "__main__":
    main()
