"""Layer 2: End-to-End Generation Quality Evaluation.

Tests the full Planner → KnowledgeRetriever → LLM chain using RAGAS v0.4.3.
Evaluates: Faithfulness, ContextPrecision, ContextRecall, AnswerRelevancy,
           FactualCorrectness, plus custom hallucination-gate metrics.

All LLM calls use DeepSeek V4 via ``evaluation.llm_factory``.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from ragas import evaluate, EvaluationDataset, SingleTurnSample
from ragas.metrics.collections import (
    ContextPrecisionWithReference,
    ContextRecall,
    Faithfulness,
    AnswerRelevancy,
    FactualCorrectness,
)

from evaluation.conftest import EVAL_USER_A
from evaluation.llm_factory import build_deepseek_llm, build_ragas_llm


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _generate_answer(query: str, user_id: str) -> dict[str, Any]:
    """Run the production knowledge retrieval + LLM generation chain."""
    from app.rag.knowledge_retriever import knowledge_retriever
    from app.rag.embeddings import agent_fast_llm

    kr = await knowledge_retriever.retrieve(
        dense_query=query,
        sparse_query=query,
        source_types=["interview_qa"],
        user_id=user_id,
    )

    contexts = [c.get("text", "") for c in kr.chunks]
    context_block = "\n\n".join(contexts[:5])

    llm = build_deepseek_llm()
    prompt = (
        "你是面试问答助手。请严格基于给定参考资料回答问题；"
        "如果资料不足，明确说资料不足，不要编造。\n\n"
        f"问题：{query}\n\n"
        f"参考资料：\n{context_block}"
    )
    response = await llm.ainvoke(prompt)
    answer = response.content if isinstance(response.content, str) else str(response.content)

    return {
        "answer": answer,
        "contexts": contexts[:5],
        "retrieval_hit": kr.retrieval_hit,
    }


def _build_ragas_samples(
    dataset: list[dict[str, Any]],
) -> tuple[list[SingleTurnSample], list[dict[str, Any]]]:
    """Run retrieval + generation for each row and build RAGAS samples."""
    samples: list[SingleTurnSample] = []
    details: list[dict[str, Any]] = []

    for row in dataset:
        user_id = row.get("user_id", EVAL_USER_A)
        result = asyncio.run(_generate_answer(row["query"], user_id))

        sample = SingleTurnSample(
            user_input=row["query"],
            response=result["answer"],
            retrieved_contexts=result["contexts"],
            reference=row.get("reference_answer", ""),
        )
        samples.append(sample)
        details.append({
            "id": row.get("id", ""),
            "query": row["query"],
            "answer_len": len(result["answer"]),
            "contexts_count": len(result["contexts"]),
            "retrieval_hit": result["retrieval_hit"],
            "empty_answer": not result["answer"].strip(),
            "hallucination_gate": not result["retrieval_hit"],
        })

    return samples, details


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGenerationQuality:
    """RAGAS-based generation quality evaluation."""

    @pytest.fixture(scope="class")
    def ragas_results(self, generation_dataset: list[dict[str, Any]]):
        """Pre-compute RAGAS evaluation results for the dataset."""
        samples, details = _build_ragas_samples(generation_dataset)
        ragas_llm = build_ragas_llm()

        metrics = [
            Faithfulness(llm=ragas_llm),
            ContextPrecisionWithReference(llm=ragas_llm),
            ContextRecall(llm=ragas_llm),
            AnswerRelevancy(llm=ragas_llm),
            FactualCorrectness(llm=ragas_llm),
        ]

        eval_dataset = EvaluationDataset(samples=samples)
        result = evaluate(
            dataset=eval_dataset,
            metrics=metrics,
            show_progress=True,
        )

        return {
            "result": result,
            "details": details,
            "scores": result.to_pandas().to_dict(orient="records"),
        }

    def test_faithfulness(self, ragas_results):
        """Average faithfulness should be ≥ 0.70."""
        scores = [
            r["faithfulness"]
            for r in ragas_results["scores"]
            if r.get("faithfulness") is not None and r["faithfulness"] == r["faithfulness"]
        ]
        if not scores:
            pytest.skip("No faithfulness scores computed.")
        avg = sum(scores) / len(scores)
        print(f"\n  Faithfulness = {avg:.4f} (n={len(scores)})")
        assert avg >= 0.70, f"Faithfulness = {avg:.4f}, expected ≥ 0.70"

    def test_context_precision(self, ragas_results):
        """Average context precision should be ≥ 0.60."""
        scores = [
            r["context_precision"]
            for r in ragas_results["scores"]
            if r.get("context_precision") is not None
            and r["context_precision"] == r["context_precision"]
        ]
        if not scores:
            pytest.skip("No context_precision scores computed.")
        avg = sum(scores) / len(scores)
        print(f"\n  Context Precision = {avg:.4f} (n={len(scores)})")
        assert avg >= 0.60, f"Context Precision = {avg:.4f}, expected ≥ 0.60"

    def test_context_recall(self, ragas_results):
        """Average context recall should be ≥ 0.60."""
        scores = [
            r["context_recall"]
            for r in ragas_results["scores"]
            if r.get("context_recall") is not None
            and r["context_recall"] == r["context_recall"]
        ]
        if not scores:
            pytest.skip("No context_recall scores computed.")
        avg = sum(scores) / len(scores)
        print(f"\n  Context Recall = {avg:.4f} (n={len(scores)})")
        assert avg >= 0.60, f"Context Recall = {avg:.4f}, expected ≥ 0.60"

    def test_answer_relevancy(self, ragas_results):
        """Average answer relevancy should be ≥ 0.65."""
        scores = [
            r["answer_relevancy"]
            for r in ragas_results["scores"]
            if r.get("answer_relevancy") is not None
            and r["answer_relevancy"] == r["answer_relevancy"]
        ]
        if not scores:
            pytest.skip("No answer_relevancy scores computed.")
        avg = sum(scores) / len(scores)
        print(f"\n  Answer Relevancy = {avg:.4f} (n={len(scores)})")
        assert avg >= 0.65, f"Answer Relevancy = {avg:.4f}, expected ≥ 0.65"

    def test_hallucination_rate(self, ragas_results):
        """Hallucination gate trigger rate should be ≤ 0.30."""
        details = ragas_results["details"]
        gate_count = sum(1 for d in details if d["hallucination_gate"])
        rate = gate_count / len(details) if details else 0.0
        print(f"\n  Hallucination Gate Rate = {rate:.4f} ({gate_count}/{len(details)})")
        assert rate <= 0.30, f"Hallucination gate rate = {rate:.4f}, expected ≤ 0.30"

    def test_empty_answer_rate(self, ragas_results):
        """Empty answer rate should be ≤ 0.10."""
        details = ragas_results["details"]
        empty = sum(1 for d in details if d["empty_answer"])
        rate = empty / len(details) if details else 0.0
        print(f"\n  Empty Answer Rate = {rate:.4f} ({empty}/{len(details)})")
        assert rate <= 0.10, f"Empty answer rate = {rate:.4f}, expected ≤ 0.10"
