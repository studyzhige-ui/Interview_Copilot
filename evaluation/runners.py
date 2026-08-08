"""Shared async runners for the three evaluation layers.

Both the CLI (``eval_runner.py``) and the pytest suite (``test_*.py``)
call into these. The contract is simple: input = a list of golden-
dataset rows, output = a metric dict. Side effects (printing, report
writing) live in the caller.

Layer mapping:
  L1 retrieval — ``run_retrieval``  : hybrid Milvus + BM25 + reranker;
                                     no LLM cost.
  L2 generation — ``run_generation``: retrieve → evaluator answer →
                                     RAGAS v0.4.3 scores. LLM-heavy.
  L3 planner   — ``run_trajectory`` : query → plan_query →
                                     routing-decision aggregates.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from evaluation.metrics import (
    aggregate_scores,
    citation_coverage,
    citation_validity,
    chunk_relevance,
    chunk_matches_terms,
    dcg,
    hit_at_k,
    has_insufficient_disclaimer,
    is_insufficient_answer,
    ndcg_at_k,
    precision_at_k,
    reciprocal_rank,
    term_coverage,
)

logger = logging.getLogger(__name__)

RAG_DATASET_PATH = Path(__file__).with_name("rag_dataset.jsonl")
DEFAULT_USER = "eval_user_a"

DEFAULT_PLANNER_CONCURRENCY = 16
_CURRENT_SOURCE_KINDS = frozenset({"user_upload", "improved_qa", "manual_text"})


@dataclass(frozen=True)
class PlannerEvaluationResult:
    """One planner outcome aligned with its input evaluation row."""

    plan: Any | None
    error: Exception | None
    latency_ms: float


async def plan_evaluation_rows(
    rows: list[dict[str, Any]],
    *,
    concurrency: int = DEFAULT_PLANNER_CONCURRENCY,
    global_memory_on: bool,
) -> list[PlannerEvaluationResult]:
    """Plan independent evaluation rows concurrently while preserving order."""
    from app.conversation.query_planner import plan_query

    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")
    semaphore = asyncio.Semaphore(concurrency)

    async def plan_row(row: dict[str, Any]) -> PlannerEvaluationResult:
        async with semaphore:
            started = time.perf_counter()
            try:
                plan = await plan_query(
                    user_message=row["query"],
                    recent_turns=[],
                    learning_strategy_description="",
                    global_memory_on=global_memory_on,
                )
                return PlannerEvaluationResult(
                    plan=plan,
                    error=None,
                    latency_ms=(time.perf_counter() - started) * 1000,
                )
            except Exception as exc:  # pragma: no cover - transport boundary
                return PlannerEvaluationResult(
                    plan=None,
                    error=exc,
                    latency_ms=(time.perf_counter() - started) * 1000,
                )

    return list(await asyncio.gather(*(plan_row(row) for row in rows)))


def _percentile(values: list[float], percentile: int) -> float:
    """Return a linearly interpolated percentile for a non-empty sample."""
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * percentile / 100
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


# ── Dataset loading ────────────────────────────────────────────────────


def load_dataset(
    limit: int | None = None,
    path: Path | None = None,
) -> list[dict[str, Any]]:
    """Load newline-delimited evaluation rows from ``path``."""
    dataset_path = path or RAG_DATASET_PATH
    if not dataset_path.exists():
        raise FileNotFoundError(
            f"Evaluation dataset missing: {dataset_path}. Run "
            "python -m evaluation.download_corpus and use the tracked "
            "evaluation/rag_dataset.jsonl, or pass --dataset explicitly."
        )
    rows: list[dict[str, Any]] = []
    with dataset_path.open(encoding="utf-8") as f:
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


def _dataset_source_kind(row: dict[str, Any]) -> str | None:
    """Use a source filter only when the dataset names a current storage kind.

    Older datasets use ``source_type=interview_qa`` as a semantic label; that
    value was never a current ``knowledge_documents.source_kind`` and must not
    accidentally filter every result.
    """
    value = row.get("source_kind") or row.get("source_type")
    return value if value in _CURRENT_SOURCE_KINDS else None


def _source_format(row: dict[str, Any]) -> str:
    """Return the user-visible source format used by evaluation slices."""
    source_files = [
        str(value).strip() for value in row.get("source_files") or [] if value
    ]
    source_file = str(row.get("source_file") or "").strip()
    if source_file:
        source_files.append(source_file)
    formats = {Path(value).suffix.lower().lstrip(".") for value in source_files}
    formats.discard("")
    if len(formats) > 1:
        return "mixed"
    return next(iter(formats), "unknown")


def _evaluation_document_id(source_file: str) -> str:
    return "kdoc_eval_" + hashlib.sha256(source_file.encode("utf-8")).hexdigest()[:24]


def _evidence_groups(
    row: dict[str, Any],
) -> list[tuple[str, tuple[tuple[str, ...], ...]]]:
    groups: list[tuple[str, tuple[tuple[str, ...], ...]]] = []
    for group in row.get("evidence_groups") or []:
        source_file = str(group.get("source_file") or "").strip()
        alternatives = tuple(
            tuple(
                str(value).strip() for value in alternative.get("all_of") or [] if value
            )
            for alternative in group.get("alternatives") or []
        )
        alternatives = tuple(value for value in alternatives if value)
        if source_file and alternatives:
            groups.append((_evaluation_document_id(source_file), alternatives))
    return groups


def _expected_document_ids(row: dict[str, Any]) -> set[str]:
    """Resolve explicit gold ids or the deterministic prepared-corpus id."""
    explicit = row.get("relevant_document_ids")
    if isinstance(explicit, list):
        return {str(value) for value in explicit if value}
    source_files = [
        str(value).strip() for value in row.get("source_files", []) if value
    ]
    source_file = str(row.get("source_file") or "").strip()
    if source_file:
        source_files.append(source_file)
    if not source_files:
        return set()
    return {_evaluation_document_id(name) for name in source_files}


def _resolve_evaluation_users(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Fail fast when the evaluation corpus cannot be tenant-scoped."""
    from app.core.user_identity import resolve_user_pk
    from app.db.database import SessionLocal

    usernames = {str(row.get("user_id") or DEFAULT_USER) for row in rows}
    resolved: dict[str, int] = {}
    with SessionLocal() as db:
        for username in usernames:
            user_pk = resolve_user_pk(db, username)
            if user_pk is None:
                raise RuntimeError(
                    f"Evaluation user {username!r} does not exist. "
                    "Create the user and index its evaluation corpus first."
                )
            resolved[username] = user_pk
    return resolved


# ── L1 retrieval ───────────────────────────────────────────────────────


def _resolve_gold_chunks(rows: list[dict[str, Any]]) -> dict[str, list[set[str]]]:
    """Resolve each evidence group onto the active chunk layout.

    Questions are anchored to source documents and verbatim evidence terms.
    This scorer maps those annotations onto the chunks produced by the active
    release configuration; the gold data is never used as retrieval input.
    """
    from app.db.database import SessionLocal
    from app.models.document_chunk import DocumentChunk

    document_ids = {
        document_id for row in rows for document_id in _expected_document_ids(row)
    }
    with SessionLocal() as db:
        chunks = (
            db.query(DocumentChunk)
            .filter(
                DocumentChunk.document_id.in_(document_ids),
                DocumentChunk.index_status == "indexed",
                DocumentChunk.deleted_at.is_(None),
            )
            .all()
            if document_ids
            else []
        )
    by_document: dict[str, list[DocumentChunk]] = {}
    for chunk in chunks:
        by_document.setdefault(str(chunk.document_id), []).append(chunk)

    resolved: dict[str, list[set[str]]] = {}
    alignment_errors: list[str] = []
    for row in rows:
        row_id = str(row.get("id") or "")
        if row.get("expected_retrieval", True) is False:
            resolved[row_id] = []
            continue
        groups: list[set[str]] = []
        for group_index, (document_id, alternatives) in enumerate(
            _evidence_groups(row),
            start=1,
        ):
            matches = {
                str(chunk.node_id)
                for chunk in by_document.get(document_id, [])
                if any(
                    term_coverage(list(phrases), chunk.text or "") == 1.0
                    for phrases in alternatives
                )
            }
            if not matches:
                alignment_errors.append(f"{row_id}:group-{group_index}")
            else:
                groups.append(matches)
        if not groups:
            alignment_errors.append(f"{row_id}:no-mapped-evidence")
        resolved[row_id] = groups
    if alignment_errors:
        failures = ", ".join(alignment_errors)
        raise RuntimeError(
            "Evidence annotations do not align with the active chunk layout: "
            f"{failures}. Rebuild or repair the dataset evidence."
        )
    return resolved


def validate_evidence_alignment(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Validate all gold groups against the currently indexed chunk layout."""
    resolved = _resolve_gold_chunks(rows)
    return {
        "samples": len(resolved),
        "evidence_groups": sum(len(groups) for groups in resolved.values()),
    }


def _evidence_flags(
    node_ids: list[str],
    evidence_groups: list[set[str]],
) -> tuple[list[bool], float]:
    """Mark only the first retrieved chunk for each evidence group as useful."""
    gains, recall = _evidence_gains(node_ids, evidence_groups)
    return [gain > 0 for gain in gains], recall


def _evidence_gains(
    node_ids: list[str],
    evidence_groups: list[set[str]],
) -> tuple[list[int], float]:
    """Count newly covered atomic evidence groups at each rank."""
    seen: set[int] = set()
    gains: list[int] = []
    for node_id in node_ids:
        matched = {
            index for index, group in enumerate(evidence_groups) if node_id in group
        }
        novel = matched - seen
        gains.append(len(novel))
        seen.update(novel)
    recall = len(seen) / len(evidence_groups) if evidence_groups else 0.0
    return gains, recall


def _ideal_evidence_dcg(evidence_groups: list[set[str]], *, k: int) -> float:
    """Return the best achievable DCG from the active chunk-level qrels."""
    masks: set[int] = set()
    node_ids = set().union(*evidence_groups) if evidence_groups else set()
    for node_id in node_ids:
        mask = sum(
            1 << index
            for index, group in enumerate(evidence_groups)
            if node_id in group
        )
        if mask:
            masks.add(mask)
    states = {0: 0.0}
    for rank in range(1, k + 1):
        next_states = dict(states)
        discount = 1.0 / math.log2(rank + 1)
        for covered, value in states.items():
            for mask in masks:
                combined = covered | mask
                gain = (combined ^ covered).bit_count()
                next_states[combined] = max(
                    next_states.get(combined, 0.0),
                    value + gain * discount,
                )
        states = next_states
    return max(states.values(), default=0.0)


def _evidence_ndcg(
    node_ids: list[str],
    evidence_groups: list[set[str]],
    *,
    k: int = 3,
) -> float:
    gains, _recall = _evidence_gains(node_ids[:k], evidence_groups)
    ideal = _ideal_evidence_dcg(evidence_groups, k=k)
    return min(dcg([float(gain) for gain in gains]) / ideal, 1.0) if ideal else 0.0


def _record_evidence_flags(
    chunks: list[dict[str, Any]],
    record: dict[str, Any],
) -> tuple[list[bool], float]:
    groups = [set(group) for group in record.get("evidence_groups") or []]
    if groups:
        return _evidence_flags(
            [str(chunk.get("node_id") or "") for chunk in chunks],
            groups,
        )
    flags = [bool(chunk.get("relevant")) for chunk in chunks]
    return flags, float(any(flags))


def _retained_chunks(
    chunks: list[dict[str, Any]],
    *,
    threshold: float,
    score_margin: float | None,
) -> list[dict[str, Any]]:
    retained = [chunk for chunk in chunks if chunk["score"] >= threshold]
    if score_margin is not None and retained:
        best_score = retained[0]["score"]
        retained = [
            chunk for chunk in retained if chunk["score"] >= best_score - score_margin
        ]
    return retained


def _threshold_metrics(
    records: list[dict[str, Any]],
    threshold: float,
    score_margin: float | None = None,
) -> dict[str, Any]:
    positive_count = sum(record["expected"] for record in records)
    negative_count = len(records) - positive_count
    true_positive = false_positive = 0
    negative_emissions = 0
    retained_chunks = 0
    relevant_retained_chunks = 0
    passage_precisions: list[float] = []
    context_precisions: list[float] = []
    mrrs: list[float] = []
    ndcgs: list[float] = []
    source_hits: list[int] = []
    evidence_recalls: list[float] = []
    document_recalls: list[float] = []
    for record in records:
        retained = _retained_chunks(
            record["chunks"],
            threshold=threshold,
            score_margin=score_margin if record.get("allow_margin", True) else None,
        )
        relevant_flags, _evidence_recall = _record_evidence_flags(retained, record)
        retained_chunks += len(retained)
        relevant_retained_chunks += sum(relevant_flags)
        emitted = bool(retained)
        correct = any(relevant_flags)
        if record["expected"] and correct:
            true_positive += 1
        elif emitted:
            false_positive += 1
        if not record["expected"] and emitted:
            negative_emissions += 1
        if record["expected"]:
            source_flags = [
                bool(chunk.get("source_match", chunk["relevant"])) for chunk in retained
            ]
            passage_precisions.append(precision_at_k(relevant_flags, k=3))
            context_precisions.append(
                sum(relevant_flags) / len(relevant_flags) if relevant_flags else 0.0
            )
            mrrs.append(reciprocal_rank(relevant_flags[:3]))
            groups = [set(group) for group in record.get("evidence_groups") or []]
            ndcgs.append(
                _evidence_ndcg(
                    [str(chunk.get("node_id") or "") for chunk in retained],
                    groups,
                )
                if groups
                else ndcg_at_k(
                    [float(flag) for flag in relevant_flags[:3]],
                    k=3,
                    total_relevant=1,
                )
            )
            source_hits.append(hit_at_k(source_flags, k=3))
            evidence_recalls.append(_record_evidence_flags(retained[:3], record)[1])
            expected_documents = set(record.get("expected_document_ids") or [])
            retrieved_documents = {
                str(chunk.get("document_id") or "") for chunk in retained[:3]
            }
            document_recalls.append(
                len(expected_documents & retrieved_documents) / len(expected_documents)
                if expected_documents
                else 0.0
            )
    precision = (
        true_positive / (true_positive + false_positive)
        if true_positive + false_positive
        else 1.0
    )
    recall = true_positive / positive_count if positive_count else 0.0
    return {
        "threshold": round(threshold, 4),
        "score_margin": score_margin,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(
            2 * precision * recall / (precision + recall)
            if precision + recall
            else 0.0,
            4,
        ),
        "negative_false_positive_rate": round(
            negative_emissions / negative_count if negative_count else 0.0,
            4,
        ),
        "evidence_precision": round(
            relevant_retained_chunks / retained_chunks if retained_chunks else 1.0,
            4,
        ),
        "relevant_retained_chunks": relevant_retained_chunks,
        "retained_chunks": retained_chunks,
        "passage_hit_at_3": round(recall, 4),
        "passage_mrr_at_3": round(sum(mrrs) / len(mrrs), 4) if mrrs else 0.0,
        "passage_ndcg_at_3": round(sum(ndcgs) / len(ndcgs), 4) if ndcgs else 0.0,
        "passage_precision_at_3": round(
            sum(passage_precisions) / len(passage_precisions), 4
        )
        if passage_precisions
        else 0.0,
        "macro_context_evidence_precision": round(
            sum(context_precisions) / len(context_precisions), 4
        )
        if context_precisions
        else 0.0,
        "source_hit_at_3": round(sum(source_hits) / len(source_hits), 4)
        if source_hits
        else 0.0,
        "evidence_group_recall_at_3": round(
            sum(evidence_recalls) / len(evidence_recalls), 4
        )
        if evidence_recalls
        else 0.0,
        "document_recall_at_3": round(sum(document_recalls) / len(document_recalls), 4)
        if document_recalls
        else 0.0,
    }


def _binary_ranking_metrics(pairs: list[tuple[float, bool]]) -> dict[str, float]:
    positives = [score for score, relevant in pairs if relevant]
    negatives = [score for score, relevant in pairs if not relevant]
    if not positives or not negatives:
        return {"auroc": 0.0, "average_precision": 0.0}
    wins = sum(
        1.0 if positive > negative else 0.5 if positive == negative else 0.0
        for positive in positives
        for negative in negatives
    )
    ranked = sorted(pairs, key=lambda pair: pair[0], reverse=True)
    seen_positive = 0
    precision_sum = 0.0
    for rank, (_score, relevant) in enumerate(ranked, 1):
        if relevant:
            seen_positive += 1
            precision_sum += seen_positive / rank
    return {
        "auroc": round(wins / (len(positives) * len(negatives)), 4),
        "average_precision": round(precision_sum / len(positives), 4),
    }


def _positive_threshold_slices(
    records: list[dict[str, Any]],
    threshold: float,
    score_margin: float | None,
    *,
    slice_key: str = "source_format",
) -> dict[str, dict[str, float | int]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        if record["expected"]:
            grouped.setdefault(str(record.get(slice_key) or "unknown"), []).append(
                record
            )
    slices: dict[str, dict[str, float | int]] = {}
    for source_format, values in sorted(grouped.items()):
        correct = retained_count = relevant_count = 0
        for record in values:
            retained = _retained_chunks(
                record["chunks"],
                threshold=threshold,
                score_margin=(
                    score_margin if record.get("allow_margin", True) else None
                ),
            )
            relevant_flags, _recall = _record_evidence_flags(retained, record)
            correct += int(any(relevant_flags))
            retained_count += len(retained)
            relevant_count += sum(relevant_flags)
        slices[source_format] = {
            "samples": len(values),
            "recall": round(correct / len(values), 4),
            "evidence_precision": round(
                relevant_count / retained_count if retained_count else 1.0,
                4,
            ),
        }
    return slices


def _calibrate_threshold(records: list[dict[str, Any]]) -> dict[str, Any]:
    calibration = [record for record in records if record["split"] == "calibration"]
    test = [record for record in records if record["split"] == "test"]
    selection_rule = (
        "absolute reranker score >= 0.80; calibration precision/recall >= "
        "0.95/0.90; negative FPR <= 0.05; exact evidence precision >= 0.55; "
        "every format recall/evidence >= 0.75/0.45; every language recall >= "
        "0.85; then maximize recall and exact evidence purity"
    )
    if not calibration:
        return {
            "selection_rule": selection_rule,
            "calibration_samples": 0,
            "test_samples": len(test),
            "recommended_threshold": None,
            "recommended_score_margin": None,
            "calibration_metrics": None,
            "calibration_by_source_format": None,
            "calibration_by_language": None,
            "held_out_test_metrics": None,
            "sweep": [],
        }
    sweep = [
        _threshold_metrics(calibration, threshold / 100, margin)
        for threshold in range(0, 100)
        for margin in (0.0, 0.01, 0.02, 0.03, 0.05, 0.08, 0.1, None)
    ]

    def eligible_for_release(result: dict[str, Any]) -> bool:
        from evaluation.retrieval_gates import (
            MAX_UNANSWERABLE_FALSE_POSITIVE_RATE,
            MIN_CALIBRATED_RERANK_SCORE,
            MIN_DEPLOYED_EVIDENCE_PRECISION,
            MIN_DEPLOYED_QUERY_PRECISION,
            MIN_DEPLOYED_QUERY_RECALL,
            MIN_DOCUMENT_RECALL_AT_3,
            MIN_EVIDENCE_GROUP_RECALL_AT_3,
            MIN_FORMAT_EVIDENCE_PRECISION,
            MIN_FORMAT_RECALL,
            MIN_LANGUAGE_RECALL,
            MIN_MACRO_CONTEXT_EVIDENCE_PRECISION,
            MIN_PASSAGE_HIT_AT_3,
            MIN_PASSAGE_MRR_AT_3,
            MIN_PASSAGE_NDCG_AT_3,
            MIN_SOURCE_HIT_AT_3,
        )

        by_format = _positive_threshold_slices(
            calibration,
            result["threshold"],
            result["score_margin"],
        )
        by_language = _positive_threshold_slices(
            calibration,
            result["threshold"],
            result["score_margin"],
            slice_key="language",
        )
        return (
            result["threshold"] >= MIN_CALIBRATED_RERANK_SCORE
            and result["precision"] >= MIN_DEPLOYED_QUERY_PRECISION
            and result["recall"] >= MIN_DEPLOYED_QUERY_RECALL
            and result["negative_false_positive_rate"]
            <= MAX_UNANSWERABLE_FALSE_POSITIVE_RATE
            and result["evidence_precision"] >= MIN_DEPLOYED_EVIDENCE_PRECISION
            and result["passage_hit_at_3"] >= MIN_PASSAGE_HIT_AT_3
            and result["source_hit_at_3"] >= MIN_SOURCE_HIT_AT_3
            and result["passage_mrr_at_3"] >= MIN_PASSAGE_MRR_AT_3
            and result["passage_ndcg_at_3"] >= MIN_PASSAGE_NDCG_AT_3
            and result["macro_context_evidence_precision"]
            >= MIN_MACRO_CONTEXT_EVIDENCE_PRECISION
            and result["evidence_group_recall_at_3"] >= MIN_EVIDENCE_GROUP_RECALL_AT_3
            and result["document_recall_at_3"] >= MIN_DOCUMENT_RECALL_AT_3
            and bool(by_format)
            and min(value["recall"] for value in by_format.values())
            >= MIN_FORMAT_RECALL
            and min(value["evidence_precision"] for value in by_format.values())
            >= MIN_FORMAT_EVIDENCE_PRECISION
            and bool(by_language)
            and min(value["recall"] for value in by_language.values())
            >= MIN_LANGUAGE_RECALL
        )

    eligible = [result for result in sweep if eligible_for_release(result)]
    selected = max(
        eligible,
        key=lambda result: (
            result["recall"],
            result["evidence_precision"],
            result["precision"],
            -result["retained_chunks"],
            result["threshold"],
        ),
        default=None,
    )
    display_thresholds = {0.0, 0.25, 0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 0.99}
    if selected:
        display_thresholds.add(selected["threshold"])
    return {
        "selection_rule": selection_rule,
        "calibration_samples": len(calibration),
        "test_samples": len(test),
        "recommended_threshold": selected["threshold"] if selected else None,
        "recommended_score_margin": selected["score_margin"] if selected else None,
        "calibration_metrics": selected,
        "calibration_by_source_format": (
            _positive_threshold_slices(
                calibration,
                selected["threshold"],
                selected["score_margin"],
            )
            if selected
            else None
        ),
        "calibration_by_language": (
            _positive_threshold_slices(
                calibration,
                selected["threshold"],
                selected["score_margin"],
                slice_key="language",
            )
            if selected
            else None
        ),
        "held_out_test_metrics": (
            _threshold_metrics(
                test,
                selected["threshold"],
                selected["score_margin"],
            )
            if selected and test
            else None
        ),
        "held_out_test_by_source_format": (
            _positive_threshold_slices(
                test,
                selected["threshold"],
                selected["score_margin"],
            )
            if selected and test
            else None
        ),
        "sweep": [
            result
            for result in sweep
            if result["threshold"] in display_thresholds
            and result["score_margin"] in {0.0, 0.03, 0.05, None}
        ],
    }


async def run_retrieval(
    rows: list[dict[str, Any]],
    *,
    query_mode: str = "direct",
    planned_rows: list[PlannerEvaluationResult] | None = None,
    planner_concurrency: int = DEFAULT_PLANNER_CONCURRENCY,
    verify_tenant_isolation: bool = False,
) -> dict[str, Any]:
    """Aggregate retrieval quality across ``rows``.

    Calls the production ``query_knowledge_base`` once per row and
    derives Hit / Precision / Recall / MRR / nDCG against the
    ``reference_answer`` (or the query itself when no reference).

    ``direct`` isolates Milvus + BM25 + the reranker with the user's literal
    question. ``planned`` first runs the production planner so bilingual query
    variants and intent decomposition match the real user path.
    """
    from app.core.config import settings
    from app.rag.contracts import SearchIntent
    from app.rag.retriever import init_reranker, query_knowledge_base

    if query_mode not in {"direct", "planned"}:
        raise ValueError("query_mode must be 'direct' or 'planned'")
    init_reranker()
    if not rows:
        return {"samples": 0, "error": "No rows."}
    if query_mode == "planned":
        planned_rows = planned_rows or await plan_evaluation_rows(
            rows,
            concurrency=planner_concurrency,
            global_memory_on=False,
        )
        if len(planned_rows) != len(rows):
            raise ValueError("planned_rows must align with rows")
    user_pks = _resolve_evaluation_users(rows)
    gold_chunks = _resolve_gold_chunks(rows)

    passage_hits: list[int] = []
    passage_hits_at_1: list[int] = []
    source_hits: list[int] = []
    semantic_hits: list[int] = []
    passage_precisions: list[float] = []
    context_evidence_precisions: list[float] = []
    reranked_hits_at_1: list[int] = []
    reranked_hits_at_3: list[int] = []
    reranked_precisions_at_3: list[float] = []
    reranked_context_precisions: list[float] = []
    reranked_evidence_group_recalls: list[float] = []
    reranked_mrrs: list[float] = []
    reranked_ndcgs: list[float] = []
    candidate_gold_hits: list[int] = []
    candidate_evidence_group_recalls: list[float] = []
    candidate_source_hits: list[int] = []
    candidate_totals: list[float] = []
    candidate_counts_per_intent: list[float] = []
    evidence_group_recalls: list[float] = []
    document_recalls: list[float] = []
    mrrs: list[float] = []
    ndcgs: list[float] = []
    latencies: list[float] = []
    isolation_violations = 0
    negative_false_positives = 0
    positive_details: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []
    threshold_records: list[dict[str, Any]] = []
    score_pairs: list[tuple[float, bool]] = []
    relevant_scores: list[float] = []
    irrelevant_scores: list[float] = []
    positive_best_scores: list[float] = []
    negative_top_scores: list[float] = []
    planner_latencies: list[float] = []
    planner_fallbacks = 0

    for idx, row in enumerate(rows, 1):
        user_id = row.get("user_id", DEFAULT_USER)
        if query_mode == "planned" and planned_rows is not None:
            planned = planned_rows[idx - 1]
            if planned.error is not None:
                raise RuntimeError(
                    f"Planner failed for evaluation sample {row.get('id', idx)!r}"
                ) from planned.error
            plan = planned.plan
            assert plan is not None
            planner_latencies.append(planned.latency_ms)
            planner_fallbacks += int(plan.planner_failed)
            intents = plan.intents
        else:
            intents = [SearchIntent.from_query(row["query"])]
        allow_margin = len(intents) == 1
        start = time.perf_counter()
        result = await query_knowledge_base(
            intents=intents,
            user_id=user_id,
            source_kind=_dataset_source_kind(row),
            min_score=0.0,
            include_diagnostics=True,
        )
        latency_ms = (time.perf_counter() - start) * 1000
        latencies.append(latency_ms)

        all_chunks = result.chunks
        score_margin = settings.RAG_SCORE_MARGIN
        retained_records = _retained_chunks(
            [
                {**chunk, "score": float(chunk.get("score") or 0.0)}
                for chunk in all_chunks
            ],
            threshold=settings.RAG_MIN_SCORE,
            score_margin=score_margin if allow_margin else None,
        )
        retained_ids = {str(chunk.get("node_id") or "") for chunk in retained_records}
        chunks = [
            chunk
            for chunk in all_chunks
            if str(chunk.get("node_id") or "") in retained_ids
        ]
        expected_retrieval = row.get("expected_retrieval", True) is not False
        ref = row.get("reference_answer", row["query"])
        reference_terms = [str(value) for value in row.get("reference_terms", [])]
        expected_ids = _expected_document_ids(row)
        expected_evidence_groups = gold_chunks[str(row.get("id") or "")]
        expected_chunk_ids = set().union(*expected_evidence_groups)
        source_flags = [
            bool(expected_ids) and str(chunk.get("document_id") or "") in expected_ids
            for chunk in chunks
        ]
        semantic_flags = [
            chunk_matches_terms(reference_terms, c.get("text", ""))
            if reference_terms
            else chunk_relevance(ref, c.get("text", ""))
            for c in chunks
        ]
        exact_flags, retained_evidence_recall = _evidence_flags(
            [str(chunk.get("node_id") or "") for chunk in chunks],
            expected_evidence_groups,
        )
        flags = exact_flags

        raw_chunk_records: list[dict[str, Any]] = []
        for chunk in all_chunks:
            exact_match = (
                bool(expected_chunk_ids)
                and str(chunk.get("node_id") or "") in expected_chunk_ids
            )
            relevant = expected_retrieval and exact_match
            score = float(chunk.get("score") or 0.0)
            raw_chunk_records.append(
                {
                    "node_id": str(chunk.get("node_id") or ""),
                    "score": score,
                    "relevant": relevant,
                    "evidence_group_ids": [
                        group_index
                        for group_index, group in enumerate(expected_evidence_groups)
                        if str(chunk.get("node_id") or "") in group
                    ],
                    "source_match": bool(expected_ids)
                    and str(chunk.get("document_id") or "") in expected_ids,
                    "document_id": str(chunk.get("document_id") or ""),
                    "text": str(chunk.get("text") or ""),
                }
            )
            score_pairs.append((score, relevant))
            (relevant_scores if relevant else irrelevant_scores).append(score)
        raw_flags, raw_evidence_recall = _evidence_flags(
            [str(chunk.get("node_id") or "") for chunk in all_chunks[:3]],
            expected_evidence_groups,
        )
        threshold_records.append(
            {
                "id": row.get("id", ""),
                "split": row.get("split") or "test",
                "expected": expected_retrieval,
                "allow_margin": allow_margin,
                "source_format": _source_format(row),
                "language": str(row.get("language") or "unknown"),
                "chunks": raw_chunk_records,
                "evidence_groups": [
                    sorted(group) for group in expected_evidence_groups
                ],
                "evidence_group_count": len(expected_evidence_groups),
                "expected_document_ids": sorted(expected_ids),
                "reference_terms": reference_terms,
            }
        )
        relevant_in_row = [
            chunk["score"] for chunk in raw_chunk_records if chunk["relevant"]
        ]
        if expected_retrieval:
            positive_best_scores.append(max(relevant_in_row, default=0.0))
        else:
            negative_top_scores.append(
                max((chunk["score"] for chunk in raw_chunk_records), default=0.0)
            )

        if expected_retrieval:
            candidate_ids = result.diagnostics.get("candidate_node_ids") or []
            candidate_document_ids = (
                result.diagnostics.get("candidate_document_ids") or []
            )
            candidate_groups = (
                result.diagnostics.get("candidate_node_ids_by_intent") or []
            )
            candidate_totals.append(float(len(candidate_ids)))
            candidate_counts_per_intent.extend(
                float(len(group)) for group in candidate_groups
            )
            candidate_gold_hits.append(
                int(bool(expected_chunk_ids & set(candidate_ids)))
            )
            candidate_evidence_group_recalls.append(
                _evidence_flags(
                    [str(value) for value in candidate_ids],
                    expected_evidence_groups,
                )[1]
            )
            candidate_source_hits.append(
                int(bool(expected_ids & set(candidate_document_ids)))
            )
            reranked_hits_at_1.append(hit_at_k(raw_flags, k=1))
            reranked_hits_at_3.append(hit_at_k(raw_flags, k=3))
            reranked_precisions_at_3.append(precision_at_k(raw_flags, k=3))
            reranked_context_precisions.append(
                sum(raw_flags[:3]) / len(raw_flags[:3]) if raw_flags else 0.0
            )
            reranked_evidence_group_recalls.append(raw_evidence_recall)
            reranked_mrrs.append(reciprocal_rank(raw_flags[:3]))
            reranked_ndcgs.append(
                _evidence_ndcg(
                    [str(chunk.get("node_id") or "") for chunk in all_chunks],
                    expected_evidence_groups,
                )
            )
            passage_hits_at_1.append(hit_at_k(flags, k=1))
            passage_hits.append(hit_at_k(flags, k=3))
            source_hits.append(hit_at_k(source_flags, k=3))
            semantic_hits.append(hit_at_k(semantic_flags, k=3))
            passage_precisions.append(precision_at_k(flags, k=3))
            context_evidence_precisions.append(
                sum(flags) / len(flags) if flags else 0.0
            )
            evidence_group_recalls.append(retained_evidence_recall)
            mrrs.append(reciprocal_rank(flags[:3]))
            retrieved_ids = {
                str(chunk.get("document_id") or "") for chunk in chunks[:3]
            }
            document_recalls.append(
                len(expected_ids & retrieved_ids) / len(expected_ids)
                if expected_ids
                else 0.0
            )
            ndcgs.append(
                _evidence_ndcg(
                    [str(chunk.get("node_id") or "") for chunk in chunks],
                    expected_evidence_groups,
                )
            )
            positive_details.append(
                {
                    "language": str(row.get("language") or "unknown"),
                    "difficulty": str(row.get("difficulty") or "unknown"),
                    "source_format": _source_format(row),
                    "hit": passage_hits[-1],
                    "reranked_hit": reranked_hits_at_3[-1],
                }
            )
        elif chunks:
            negative_false_positives += 1

        details.append(
            {
                "id": row.get("id", ""),
                "query": row["query"],
                "language": row.get("language", "unknown"),
                "difficulty": row.get("difficulty", "unknown"),
                "source_format": _source_format(row),
                "expected_retrieval": expected_retrieval,
                "passage_hit_at_3": hit_at_k(flags, k=3)
                if expected_retrieval
                else None,
                "passage_hit_at_1": hit_at_k(flags, k=1)
                if expected_retrieval
                else None,
                "reranked_passage_hit_at_3": hit_at_k(raw_flags, k=3)
                if expected_retrieval
                else None,
                "source_hit_at_3": hit_at_k(source_flags, k=3)
                if expected_retrieval
                else None,
                "document_recall_at_3": (
                    len(
                        expected_ids
                        & {str(chunk.get("document_id") or "") for chunk in chunks[:3]}
                    )
                    / len(expected_ids)
                )
                if expected_ids
                else None,
                "evidence_group_recall_at_3": (
                    evidence_group_recalls[-1] if expected_retrieval else None
                ),
                "returned_chunks": len(chunks),
                "raw_reranked_chunks": len(all_chunks),
                "intent_count": len(intents),
                "candidate_count": len(
                    result.diagnostics.get("candidate_node_ids") or []
                ),
                "candidate_gold_hit_at_budget": (
                    candidate_gold_hits[-1] if expected_retrieval else None
                ),
                "candidate_evidence_group_recall_at_budget": (
                    candidate_evidence_group_recalls[-1] if expected_retrieval else None
                ),
                "latency_ms": round(latency_ms, 1),
                "top_chunks": [
                    {
                        "document_id": chunk.get("document_id"),
                        "node_id": chunk.get("node_id"),
                        "score": round(float(chunk.get("score") or 0.0), 6),
                        "relevant": flags[rank],
                        "text": str(chunk.get("text") or "")[:240],
                    }
                    for rank, chunk in enumerate(chunks[:3])
                ],
                "raw_top_chunks": [
                    {
                        "document_id": chunk.get("document_id"),
                        "node_id": chunk.get("node_id"),
                        "score": round(float(chunk.get("score") or 0.0), 6),
                        "relevant": raw_flags[rank],
                    }
                    for rank, chunk in enumerate(all_chunks[:3])
                ],
            }
        )

        # Multi-tenant leakage check — any chunk tagged with a different
        # user_id than the requester is a hard isolation failure.
        for c in chunks:
            c_user = c.get("user_id")
            if c_user is not None and c_user != user_pks[user_id]:
                isolation_violations += 1

        logger.info(
            "[L1 %d/%d] hit=%d p@3=%.2f latency=%.0fms",
            idx,
            len(rows),
            passage_hits[-1] if expected_retrieval else int(bool(chunks)),
            passage_precisions[-1] if expected_retrieval else 0.0,
            latency_ms,
        )

    n = len(passage_hits)
    negative_count = len(rows) - n
    deployed = _threshold_metrics(
        threshold_records,
        settings.RAG_MIN_SCORE,
        settings.RAG_SCORE_MARGIN,
    )
    calibration = _calibrate_threshold(threshold_records)
    reranker_score_separation = _binary_ranking_metrics(score_pairs)
    tenant_isolation_probe = None
    if verify_tenant_isolation:
        from evaluation.isolation_probe import run_tenant_isolation_probe

        tenant_isolation_probe = await run_tenant_isolation_probe(
            foreign_user=DEFAULT_USER
        )
    return {
        "query_mode": query_mode,
        "samples": len(rows),
        "answerable_samples": n,
        "unanswerable_samples": negative_count,
        "candidate_budget_per_intent": settings.RAG_CANDIDATE_COUNT,
        "candidate_gold_chunk_hit_rate_at_budget": (
            round(sum(candidate_gold_hits) / n, 4) if n else None
        ),
        "candidate_source_hit_rate_at_budget": (
            round(sum(candidate_source_hits) / n, 4) if n else None
        ),
        "candidate_evidence_group_recall_at_budget": (
            round(sum(candidate_evidence_group_recalls) / n, 4) if n else None
        ),
        "candidate_total_count": aggregate_scores(candidate_totals),
        "candidate_count_per_intent": aggregate_scores(candidate_counts_per_intent),
        "reranked_passage_hit_at_1": (
            round(sum(reranked_hits_at_1) / n, 4) if n else None
        ),
        "reranked_passage_hit_at_3": (
            round(sum(reranked_hits_at_3) / n, 4) if n else None
        ),
        "reranked_passage_precision_at_3": (
            round(sum(reranked_precisions_at_3) / n, 4) if n else None
        ),
        "reranked_macro_context_evidence_precision": (
            round(sum(reranked_context_precisions) / n, 4) if n else None
        ),
        "reranked_evidence_group_recall_at_3": (
            round(sum(reranked_evidence_group_recalls) / n, 4) if n else None
        ),
        "reranked_passage_mrr_at_3": (round(sum(reranked_mrrs) / n, 4) if n else None),
        "reranked_passage_ndcg_at_3": (
            round(sum(reranked_ndcgs) / n, 4) if n else None
        ),
        "passage_hit_at_1": round(sum(passage_hits_at_1) / n, 4) if n else None,
        "passage_hit_at_3": round(sum(passage_hits) / n, 4) if n else None,
        "source_hit_at_3": round(sum(source_hits) / n, 4) if n else None,
        "semantic_hit_at_3": round(sum(semantic_hits) / n, 4) if n else None,
        "passage_precision_at_3": (
            round(sum(passage_precisions) / n, 4) if n else None
        ),
        "macro_context_evidence_precision": (
            round(sum(context_evidence_precisions) / n, 4) if n else None
        ),
        "evidence_group_recall_at_3": (
            round(sum(evidence_group_recalls) / n, 4) if n else None
        ),
        "document_recall_at_3": round(sum(document_recalls) / n, 4) if n else None,
        "passage_mrr_at_3": round(sum(mrrs) / n, 4) if n else None,
        "passage_ndcg_at_3": round(sum(ndcgs) / n, 4) if n else None,
        "unanswerable_retrieval_false_positive_rate": (
            round(negative_false_positives / negative_count, 4)
            if negative_count
            else None
        ),
        "deployed_threshold": settings.RAG_MIN_SCORE,
        "deployed_score_margin": settings.RAG_SCORE_MARGIN,
        "deployed_threshold_metrics": deployed,
        "deployed_threshold_by_source_format": _positive_threshold_slices(
            threshold_records,
            settings.RAG_MIN_SCORE,
            settings.RAG_SCORE_MARGIN,
        ),
        "deployed_threshold_by_language": _positive_threshold_slices(
            threshold_records,
            settings.RAG_MIN_SCORE,
            settings.RAG_SCORE_MARGIN,
            slice_key="language",
        ),
        "threshold_calibration": calibration,
        "reranker_score_separation": reranker_score_separation,
        "relevant_reranker_scores": aggregate_scores(relevant_scores),
        "irrelevant_reranker_scores": aggregate_scores(irrelevant_scores),
        "best_relevant_score_per_answerable_query": aggregate_scores(
            positive_best_scores
        ),
        "top_score_per_unanswerable_query": aggregate_scores(negative_top_scores),
        "passage_hit_at_3_by_language": _slice_hit_rates(positive_details, "language"),
        "reranked_passage_hit_at_3_by_language": _slice_hit_rates(
            positive_details,
            "language",
            value_key="reranked_hit",
        ),
        "passage_hit_at_3_by_difficulty": _slice_hit_rates(
            positive_details, "difficulty"
        ),
        "passage_hit_at_3_by_source_format": _slice_hit_rates(
            positive_details, "source_format"
        ),
        "reranked_passage_hit_at_3_by_source_format": _slice_hit_rates(
            positive_details,
            "source_format",
            value_key="reranked_hit",
        ),
        "latency_ms": aggregate_scores(latencies),
        "planner_latency_ms": (
            aggregate_scores(planner_latencies) if planner_latencies else None
        ),
        "planner_concurrency": (
            planner_concurrency if query_mode == "planned" else None
        ),
        "planner_fallbacks": planner_fallbacks if query_mode == "planned" else None,
        "isolation_violations": isolation_violations,
        "tenant_isolation_probe": tenant_isolation_probe,
        "per_sample_details": details,
    }


def _slice_hit_rates(
    details: list[dict[str, Any]],
    key: str,
    *,
    value_key: str = "hit",
) -> dict[str, float]:
    grouped: dict[str, list[int]] = {}
    for detail in details:
        grouped.setdefault(str(detail[key]), []).append(int(detail[value_key]))
    return {
        name: round(sum(values) / len(values), 4)
        for name, values in sorted(grouped.items())
    }


# ── L2 generation ──────────────────────────────────────────────────────


async def _run_generation(
    rows: list[dict[str, Any]],
    *,
    judge_limit: int = 0,
    retry_ragas_errors: bool = False,
    retry_unknown_paid_calls: bool = False,
    planned_rows: list[PlannerEvaluationResult] | None = None,
    planner_concurrency: int = DEFAULT_PLANNER_CONCURRENCY,
    planner_snapshot_path: Path | None = None,
) -> dict[str, Any]:
    """End-to-end RAG quality: retrieve, answer, and optionally run RAGAS.

    Pulls per-row context via the same ``knowledge_retriever`` the
    production engine uses, then has the configured evaluator answer the question
    grounded in those chunks. The CLI may include extra hard negatives in
    ``rows`` while limiting RAGAS judging to the fixed answerable subset.
    """
    from app.rag.knowledge_retriever import knowledge_retriever
    from app.rag.retrieval_state import (
        EMPTY_PLANNER_NO_RETRIEVAL,
        RetrievalResult,
        RetrievalState,
    )
    from app.rag.retriever import init_reranker
    from app.rag.evidence import check_evidence

    from evaluation.llm_factory import build_evaluation_llm
    from evaluation.ragas_runner import (
        _record_compatibility_check,
        METRIC_KEYS,
        compatibility_metric_proof,
        formal_sample_manifest,
        invalidate_compatibility_check,
        load_generation_answer,
        load_or_create_generation_answer,
        persist_generation_snapshot,
        require_compatibility_check,
        require_compatibility_answer_cache,
        require_compatibility_metric_cache,
        score_with_ragas,
    )

    if not rows:
        return {"samples": 0, "error": "No rows."}
    if judge_limit < 0:
        raise ValueError("judge_limit cannot be negative")
    if judge_limit in {1, 50}:
        pinned_ids = [str(value) for value in formal_sample_manifest()["sample_ids"]]
        expected_ids = pinned_ids[:1] if judge_limit == 1 else pinned_ids
        answerable_ids = [
            str(row.get("id") or "")
            for row in rows
            if row.get("expected_retrieval") is True
        ]
        invalid_negatives = [
            str(row.get("id") or "")
            for row in rows
            if row.get("expected_retrieval") is not True
            and (
                row.get("expected_retrieval") is not False or row.get("split") != "test"
            )
        ]
        if answerable_ids != expected_ids or invalid_negatives:
            raise ValueError(
                "Fixed RAGAS workflow requires the pinned answerable sample order "
                "and test-only negatives"
            )
        if judge_limit == 1 and len(rows) != 1:
            raise ValueError("Compatibility check must contain exactly one row")
    init_reranker()
    if judge_limit == 50:
        require_compatibility_check()
    elif judge_limit == 1:
        invalidate_compatibility_check()
    tenant_isolation_probe = None
    if judge_limit:
        from evaluation.isolation_probe import run_tenant_isolation_probe

        tenant_isolation_probe = await run_tenant_isolation_probe(
            foreign_user=DEFAULT_USER
        )

    llm = build_evaluation_llm()
    user_pks = _resolve_evaluation_users(rows)
    scored_data: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []
    model_ttft_list: list[float] = []
    end_to_end_ttft_list: list[float] = []
    retrieval_to_first_token_list: list[float] = []
    generation_e2e_list: list[float] = []
    post_planner_e2e_list: list[float] = []
    e2e_list: list[float] = []
    tpot_list: list[float] = []
    throughput_list: list[float] = []
    chunk_gaps: list[float] = []
    output_token_counts: list[float] = []
    retrieval_latencies: list[float] = []
    planner_latencies: list[float] = []
    planner_fallbacks = 0
    planner_false_negatives = 0
    generation_cache_hits = 0
    generator_live_probe = False
    first_answer_cache_path: Path | None = None
    reused_check_answer = False
    reused_check_metric_count = 0

    if planned_rows is None:
        if planner_snapshot_path is None:
            planned_rows = await plan_evaluation_rows(
                rows,
                concurrency=planner_concurrency,
                global_memory_on=True,
            )
        else:
            from evaluation.planner_snapshot import load_or_create_planner_snapshot

            planned_rows = await load_or_create_planner_snapshot(
                rows,
                path=planner_snapshot_path,
                concurrency=planner_concurrency,
                global_memory_on=True,
                retry_unknown_paid_calls=retry_unknown_paid_calls,
            )
    if len(planned_rows) != len(rows):
        raise ValueError("planned_rows must align with rows")

    for idx, row in enumerate(rows, 1):
        user_id = row.get("user_id", DEFAULT_USER)

        # ── Production planner + retrieval ──
        t_start = time.perf_counter()
        planned = planned_rows[idx - 1]
        if planned.error is not None:
            raise RuntimeError(
                f"Planner failed for evaluation sample {row.get('id', idx)!r}"
            ) from planned.error
        plan = planned.plan
        assert plan is not None
        planner_ms = planned.latency_ms
        planner_latencies.append(planner_ms)
        planner_fallbacks += int(plan.planner_failed)
        expected_retrieval = row.get("expected_retrieval", True) is not False
        if expected_retrieval and not plan.needs_knowledge_retrieval:
            planner_false_negatives += 1

        retrieval_start = time.perf_counter()
        if plan.needs_knowledge_retrieval:
            kr = await knowledge_retriever.retrieve(
                intents=plan.intents,
                user_id=user_id,
                source_kind=_dataset_source_kind(row),
            )
        else:
            kr = RetrievalResult(
                state=RetrievalState(
                    retrieval_hit=False,
                    empty_reason=EMPTY_PLANNER_NO_RETRIEVAL,
                )
            )
        if any(
            chunk.get("user_id") is not None
            and chunk.get("user_id") != user_pks[user_id]
            for chunk in kr.chunks
        ):
            raise RuntimeError(f"Cross-tenant context returned for {user_id!r}")
        retrieval_ms = (time.perf_counter() - retrieval_start) * 1000
        retrieval_latencies.append(retrieval_ms)

        contexts = [c.get("text", "") for c in kr.chunks]
        evidence = check_evidence(
            plan.intents,
            (
                f"{chunk.get('document_title') or ''}\n{chunk.get('text') or ''}"
                for chunk in kr.chunks
            ),
        )
        context_block = "\n\n".join(
            f"[K{context_index}] {context}"
            for context_index, context in enumerate(contexts, start=1)
        )

        prompt = (
            "你是面试问答助手。请严格基于给定参考资料回答问题；"
            "每个事实句末尾必须用 [K1] 形式标注所依据的资料编号。"
            "只回答问题直接要求的内容，限 2 至 5 句。"
            "使用与问题相同的语言回答。"
            "问题中的产品、版本、系统和限定条件必须在资料中明确出现；"
            "相近技术的通用信息不能替代特定对象的证据。"
            "缺少限定对象证据时直接说明缺口，不展开相近对象的背景知识。"
            "如果资料不足，明确说资料不足，不要用常识补全或编造。\n\n"
            f"问题：{row['query']}\n\n"
            f"参考资料：\n{context_block}"
        )

        generation_cache_item = {
            "id": row.get("id", ""),
            "request": {
                "prompt": prompt,
                "deterministic_response": None,
            },
        }
        # ── Generation (stream for user-visible latency metrics) ──
        can_generate = bool(contexts) and evidence.supported
        refusal_answer = (
            "现有资料不足，无法可靠回答这个问题。"
            if row.get("language") == "zh"
            else "The available sources do not contain enough evidence "
            "to answer reliably."
        )
        if not can_generate:
            generation_cache_item["request"] = {
                "prompt": None,
                "deterministic_response": refusal_answer,
            }
        cache_hit = False

        async def generate_measurement() -> dict[str, Any]:
            nonlocal generator_live_probe
            measured = (
                await _measure_stream(llm, prompt)
                if can_generate
                else StreamMeasurement(
                    answer=refusal_answer,
                    ttft_ms=None,
                    e2e_ms=0.0,
                    output_tokens=_estimated_token_count(refusal_answer),
                    token_count_source="local_estimate",
                    tpot_ms=None,
                    output_throughput_tps=None,
                    chunk_gaps_ms=[],
                    fallback=False,
                )
            )
            if can_generate:
                generator_live_probe = (
                    generator_live_probe or _is_successful_live_generation(measured)
                )
            return asdict(measured)

        if judge_limit:
            if judge_limit == 50 and idx == 1:
                measurement, first_answer_cache_path = load_generation_answer(
                    generation_cache_item
                )
                if measurement is None:
                    raise RuntimeError(
                        "Formal RAGAS cannot start because the compatibility-check "
                        "answer cache is missing"
                    )
                require_compatibility_answer_cache(first_answer_cache_path)
                cache_hit = True
                reused_check_answer = True
            else:
                (
                    measurement,
                    answer_cache_path,
                    cache_hit,
                ) = await load_or_create_generation_answer(
                    generation_cache_item,
                    generate_measurement,
                    retry_unknown_paid_calls=retry_unknown_paid_calls,
                    force_refresh=judge_limit == 1,
                )
                if judge_limit == 1:
                    first_answer_cache_path = answer_cache_path
            stream = StreamMeasurement(**measurement)
            generation_cache_hits += int(cache_hit)
        else:
            stream = StreamMeasurement(**(await generate_measurement()))
        answer = stream.answer
        live_measurement = can_generate and not cache_hit
        post_planner_e2e_ms = (
            (time.perf_counter() - t_start) * 1000 if live_measurement else None
        )
        e2e_ms = (
            planner_ms + post_planner_e2e_ms
            if post_planner_e2e_ms is not None
            else None
        )
        if post_planner_e2e_ms is not None:
            post_planner_e2e_list.append(post_planner_e2e_ms)
        if e2e_ms is not None:
            e2e_list.append(e2e_ms)
        if live_measurement:
            generation_e2e_list.append(stream.e2e_ms)
        output_token_counts.append(float(stream.output_tokens))
        chunk_gaps.extend(stream.chunk_gaps_ms)
        if live_measurement and stream.ttft_ms is not None:
            model_ttft_list.append(stream.ttft_ms)
            retrieval_to_first_token_list.append(retrieval_ms + stream.ttft_ms)
            end_to_end_ttft_list.append(planner_ms + retrieval_ms + stream.ttft_ms)
        if live_measurement and stream.tpot_ms is not None:
            tpot_list.append(stream.tpot_ms)
        if live_measurement and stream.output_throughput_tps is not None:
            throughput_list.append(stream.output_throughput_tps)

        answer_term_coverage = (
            term_coverage(
                [str(value) for value in row.get("reference_terms", [])], answer
            )
            if expected_retrieval and row.get("reference_terms")
            else None
        )
        if expected_retrieval:
            scored_data.append(
                {
                    "id": row.get("id", ""),
                    "language": row.get("language", "unknown"),
                    "difficulty": row.get("difficulty", "unknown"),
                    "source_format": _source_format(row),
                    "domain": row.get("domain", "unknown"),
                    "user_input": row["query"],
                    "response": answer,
                    "retrieved_contexts": contexts,
                    "reference": row.get("reference_answer", ""),
                }
            )
            if judge_limit == 50 and idx == 1:
                require_compatibility_metric_cache(scored_data[-1])
                reused_check_metric_count = len(METRIC_KEYS)
        citation_valid = citation_validity(answer, len(contexts))
        citation_covered = citation_coverage(answer)
        details.append(
            {
                "id": row.get("id", ""),
                "query": row["query"],
                "language": row.get("language", "unknown"),
                "difficulty": row.get("difficulty", "unknown"),
                "expected_retrieval": expected_retrieval,
                "retrieval_hit": kr.retrieval_hit,
                "planner_retrieval": plan.needs_knowledge_retrieval,
                "planner_failed": plan.planner_failed,
                "planner_intents": [intent.model_dump() for intent in plan.intents],
                "planner_ms": round(planner_ms, 1),
                "retrieval_empty_reason": kr.state.empty_reason,
                "returned_chunks": len(kr.chunks),
                "empty_answer": not answer.strip(),
                "insufficient_answer": is_insufficient_answer(answer),
                "insufficient_disclaimer": has_insufficient_disclaimer(answer),
                "retrieval_ms": round(retrieval_ms, 1),
                "measurement_source": "cache" if cache_hit else "live",
                "model_ttft_ms": round(stream.ttft_ms, 1)
                if live_measurement and stream.ttft_ms is not None
                else None,
                "retrieval_to_first_token_ms": round(retrieval_ms + stream.ttft_ms, 1)
                if live_measurement and stream.ttft_ms is not None
                else None,
                "reconstructed_end_to_end_ttft_ms": round(
                    planner_ms + retrieval_ms + stream.ttft_ms, 1
                )
                if live_measurement and stream.ttft_ms is not None
                else None,
                "generation_e2e_ms": round(stream.e2e_ms, 1)
                if live_measurement
                else None,
                "post_planner_e2e_ms": round(post_planner_e2e_ms, 1)
                if post_planner_e2e_ms is not None
                else None,
                "reconstructed_e2e_ms": round(e2e_ms, 1)
                if e2e_ms is not None
                else None,
                "output_tokens": stream.output_tokens,
                "token_count_source": stream.token_count_source,
                "tpot_ms": round(stream.tpot_ms, 2)
                if stream.tpot_ms is not None
                else None,
                "output_throughput_tps": round(stream.output_throughput_tps, 2)
                if stream.output_throughput_tps is not None
                else None,
                "stream_fallback": stream.fallback,
                "generation_mode": "llm" if can_generate else "deterministic_refusal",
                "generation_cache_hit": cache_hit,
                "evidence_guard_refusal": bool(contexts) and not evidence.supported,
                "missing_required_terms": list(evidence.missing_terms),
                "answer_reference_term_coverage": answer_term_coverage,
                "citation_validity": round(citation_valid, 4)
                if citation_valid is not None
                else None,
                "citation_coverage": round(citation_covered, 4)
                if citation_covered is not None
                else None,
                "answer": answer,
            }
        )
        logger.info(
            "[L2 %d/%d] %d tokens | ret=%.0fms ttft=%s e2e=%.0fms",
            idx,
            len(rows),
            stream.output_tokens,
            retrieval_ms,
            f"{stream.ttft_ms:.0f}ms" if stream.ttft_ms is not None else "n/a",
            e2e_ms or 0.0,
        )

    if judge_limit and len(scored_data) != judge_limit:
        raise ValueError(
            f"RAGAS expected {judge_limit} answerable rows, got {len(scored_data)}"
        )
    if judge_limit == 1 and not generator_live_probe:
        raise RuntimeError(
            "Compatibility check did not reach the answer generator; fix retrieval "
            "or evidence gating before spending judge requests"
        )
    if judge_limit:
        ragas_input, snapshot_path = persist_generation_snapshot(scored_data)
        ragas_scores = await score_with_ragas(
            ragas_input,
            retry_errors=retry_ragas_errors,
            retry_unknown_paid_calls=retry_unknown_paid_calls,
            force_live=judge_limit == 1,
        )
        ragas_scores["ragas_generation_snapshot_path"] = str(snapshot_path)
        if ragas_scores.get(
            "ragas_completed_samples"
        ) != judge_limit or ragas_scores.get("ragas_error_count"):
            raise RuntimeError(
                "RAGAS did not persist every required sample/metric; "
                "rerun with --retry-ragas-errors after fixing the cause"
            )
        if judge_limit == 1:
            judge_live_requests = int(
                (ragas_scores.get("judge_usage_this_run") or {}).get("requests") or 0
            )
            if not generator_live_probe or judge_live_requests < 1:
                raise RuntimeError(
                    "RAGAS compatibility check must reach both live providers"
                )
            if first_answer_cache_path is None:
                raise RuntimeError("Compatibility check did not persist its answer")
            ragas_scores["ragas_compatibility_marker"] = str(
                _record_compatibility_check(
                    generator_live_probe=generator_live_probe,
                    judge_live_requests=judge_live_requests,
                    answer_cache_fingerprint=first_answer_cache_path.stem,
                    metric_cache_proof=compatibility_metric_proof(scored_data[0]),
                )
            )
    else:
        ragas_scores = {
            "ragas_judged_samples": 0,
            "ragas_answerable_samples": len(scored_data),
        }

    answerable = [detail for detail in details if detail["expected_retrieval"]]
    unanswerable = [detail for detail in details if not detail["expected_retrieval"]]
    grounded_answers = [
        detail for detail in answerable if detail["generation_mode"] == "llm"
    ]
    cited = [
        detail for detail in grounded_answers if detail["citation_validity"] is not None
    ]
    summary: dict[str, Any] = {
        "samples": len(rows),
        "answerable_samples": len(answerable),
        "unanswerable_samples": len(unanswerable),
    }
    summary.update(ragas_scores)
    summary["answerable_retrieval_miss_rate"] = (
        round(sum(1 for d in answerable if not d["retrieval_hit"]) / len(answerable), 4)
        if answerable
        else None
    )
    summary["unanswerable_retrieval_false_positive_rate"] = (
        round(sum(1 for d in unanswerable if d["retrieval_hit"]) / len(unanswerable), 4)
        if unanswerable
        else None
    )
    summary["empty_answer_rate"] = round(
        sum(1 for d in details if d["empty_answer"]) / len(details),
        4,
    )
    summary["request_success_rate"] = round(
        sum(1 for d in details if not d["empty_answer"]) / len(details), 4
    )
    summary["stream_fallback_rate"] = round(
        sum(1 for d in details if d["stream_fallback"]) / len(details), 4
    )
    model_requests = [
        detail for detail in details if detail["generation_mode"] == "llm"
    ]
    summary["model_request_samples"] = len(model_requests)
    summary["deterministic_refusal_samples"] = len(details) - len(model_requests)
    summary["generation_cache_hits"] = generation_cache_hits
    summary["live_generation_measurement_samples"] = len(model_ttft_list)
    summary["cached_generation_measurement_samples"] = generation_cache_hits
    summary["reused_check_answer"] = reused_check_answer
    summary["reused_check_metric_count"] = reused_check_metric_count
    summary["tenant_isolation_probe"] = tenant_isolation_probe
    summary["unanswerable_refusal_accuracy"] = (
        round(
            sum(1 for d in unanswerable if d["insufficient_disclaimer"])
            / len(unanswerable),
            4,
        )
        if unanswerable
        else None
    )
    summary["answerable_false_refusal_rate"] = (
        round(
            sum(1 for d in answerable if d["insufficient_answer"]) / len(answerable),
            4,
        )
        if answerable
        else None
    )
    guarded_answerable = [
        detail for detail in answerable if detail["evidence_guard_refusal"]
    ]
    summary["answerable_evidence_guard_refusal_rate"] = (
        round(len(guarded_answerable) / len(answerable), 4) if answerable else None
    )
    summary["citation_emission_rate"] = (
        round(len(cited) / len(grounded_answers), 4) if grounded_answers else None
    )
    summary["citation_validity"] = (
        round(sum(float(d["citation_validity"]) for d in cited) / len(cited), 4)
        if cited
        else None
    )
    coverage = [
        float(d["citation_coverage"])
        for d in grounded_answers
        if d["citation_coverage"] is not None
    ]
    summary["citation_coverage"] = (
        round(sum(coverage) / len(coverage), 4) if coverage else None
    )
    term_coverages = [
        float(detail["answer_reference_term_coverage"])
        for detail in answerable
        if detail["answer_reference_term_coverage"] is not None
    ]
    summary["answer_reference_term_coverage"] = (
        round(sum(term_coverages) / len(term_coverages), 4) if term_coverages else None
    )
    summary["retrieval_latency_ms"] = aggregate_scores(retrieval_latencies)
    summary["planner_latency_ms"] = aggregate_scores(planner_latencies)
    summary["planner_fallback_rate"] = round(planner_fallbacks / len(rows), 4)
    summary["planner_false_negative_rate"] = (
        round(planner_false_negatives / len(answerable), 4) if answerable else None
    )
    summary["model_ttft_ms"] = aggregate_scores(model_ttft_list)
    summary["retrieval_to_first_token_ms"] = aggregate_scores(
        retrieval_to_first_token_list
    )
    summary["reconstructed_end_to_end_ttft_ms"] = aggregate_scores(end_to_end_ttft_list)
    summary["generation_e2e_latency_ms"] = aggregate_scores(generation_e2e_list)
    summary["post_planner_e2e_latency_ms"] = aggregate_scores(post_planner_e2e_list)
    summary["reconstructed_e2e_latency_ms"] = aggregate_scores(e2e_list)
    summary["tpot_ms"] = aggregate_scores(tpot_list)
    summary["stream_chunk_gap_ms"] = aggregate_scores(chunk_gaps)
    summary["output_tokens"] = aggregate_scores(output_token_counts)
    summary["output_throughput_tokens_per_second"] = aggregate_scores(throughput_list)
    summary["api_token_count_rate"] = (
        round(
            sum(1 for d in model_requests if d["token_count_source"] == "api_usage")
            / len(model_requests),
            4,
        )
        if model_requests
        else None
    )
    summary["per_sample_details"] = details
    if planner_snapshot_path is not None:
        from evaluation.planner_snapshot import (
            planner_attempt_metrics,
            planner_results_sha256,
        )

        summary["planner_results_sha256"] = planner_results_sha256(
            rows,
            planned_rows,
        )
        summary["planner_reliability"] = planner_attempt_metrics(
            planner_snapshot_path,
            rows,
            global_memory_on=True,
        )
    return summary


async def run_generation(
    rows: list[dict[str, Any]],
    *,
    judge_limit: int = 0,
    retry_ragas_errors: bool = False,
    retry_unknown_paid_calls: bool = False,
    planned_rows: list[PlannerEvaluationResult] | None = None,
    planner_concurrency: int = DEFAULT_PLANNER_CONCURRENCY,
    planner_snapshot_path: Path | None = None,
) -> dict[str, Any]:
    """Run generation, serializing the complete paid check/formal lifecycle."""
    kwargs = {
        "judge_limit": judge_limit,
        "retry_ragas_errors": retry_ragas_errors,
        "retry_unknown_paid_calls": retry_unknown_paid_calls,
        "planned_rows": planned_rows,
        "planner_concurrency": planner_concurrency,
        "planner_snapshot_path": planner_snapshot_path,
    }
    if judge_limit not in {1, 50}:
        return await _run_generation(rows, **kwargs)

    from evaluation.ragas_runner import generation_workflow_lock

    with generation_workflow_lock():
        return await _run_generation(rows, **kwargs)


@dataclass
class StreamMeasurement:
    answer: str
    ttft_ms: float | None
    e2e_ms: float
    output_tokens: int
    token_count_source: str
    tpot_ms: float | None
    output_throughput_tps: float | None
    chunk_gaps_ms: list[float]
    fallback: bool


def _is_successful_live_generation(measurement: StreamMeasurement) -> bool:
    return (
        bool(measurement.answer.strip())
        and measurement.ttft_ms is not None
        and measurement.output_tokens > 0
    )


def _estimated_token_count(text: str) -> int:
    try:
        import tiktoken

        return max(1, len(tiktoken.get_encoding("cl100k_base").encode(text)))
    except Exception:
        return max(1, len(text) // 3)


def _output_tokens_from_chunk(chunk: Any) -> int | None:
    usage = getattr(chunk, "usage_metadata", None)
    if isinstance(usage, dict):
        value = usage.get("output_tokens")
        if isinstance(value, int):
            return value
    metadata = getattr(chunk, "response_metadata", None)
    if isinstance(metadata, dict):
        token_usage = metadata.get("token_usage")
        if isinstance(token_usage, dict):
            value = token_usage.get("completion_tokens")
            if isinstance(value, int):
                return value
    return None


async def _measure_stream(llm, prompt: str) -> StreamMeasurement:
    """Measure first non-empty token, decode duration and stream jitter."""
    t_start = time.perf_counter()
    first_content_at: float | None = None
    content_times: list[float] = []
    parts: list[str] = []
    output_tokens: int | None = None
    async for chunk in llm.astream(prompt):
        content = chunk.content if hasattr(chunk, "content") else str(chunk)
        if content:
            now = time.perf_counter()
            if first_content_at is None:
                first_content_at = now
            content_times.append(now)
            parts.append(content if isinstance(content, str) else str(content))
        output_tokens = _output_tokens_from_chunk(chunk) or output_tokens

    finished_at = time.perf_counter()
    answer = "".join(parts)
    token_source = "api_usage" if output_tokens is not None else "cl100k_estimate"
    output_tokens = output_tokens or _estimated_token_count(answer)
    ttft_ms = (
        (first_content_at - t_start) * 1000 if first_content_at is not None else None
    )
    decode_seconds = (
        finished_at - first_content_at if first_content_at is not None else None
    )
    tpot_ms = (
        decode_seconds * 1000 / (output_tokens - 1)
        if decode_seconds is not None and output_tokens > 1
        else None
    )
    throughput = (
        (output_tokens - 1) / decode_seconds
        if decode_seconds is not None and decode_seconds > 0 and output_tokens > 1
        else None
    )
    gaps = [
        (current - previous) * 1000
        for previous, current in zip(content_times, content_times[1:])
    ]
    return StreamMeasurement(
        answer=answer,
        ttft_ms=ttft_ms,
        e2e_ms=(finished_at - t_start) * 1000,
        output_tokens=output_tokens,
        token_count_source=token_source,
        tpot_ms=tpot_ms,
        output_throughput_tps=throughput,
        chunk_gaps_ms=gaps,
        fallback=False,
    )


# ── L3 planner routing ─────────────────────────────────────────────────


async def run_trajectory(
    rows: list[dict[str, Any]],
    *,
    concurrency: int = DEFAULT_PLANNER_CONCURRENCY,
    planned_rows: list[PlannerEvaluationResult] | None = None,
    planner_snapshot_path: Path | None = None,
    retry_unknown_paid_calls: bool = False,
) -> dict[str, Any]:
    """Aggregate planner routing decisions across ``rows``.

    Knowledge questions, answerable or not, should trigger retrieval because
    the planner cannot know corpus coverage in advance. Intent-count accuracy is
    scored only where that decomposition was explicitly annotated. A passage-
    backed question still tests routing, but one source does not imply one ideal
    search intent.
    """
    if not rows:
        return {"samples": 0, "error": "No rows."}
    if planned_rows is None:
        if planner_snapshot_path is None:
            planned_rows = await plan_evaluation_rows(
                rows,
                concurrency=concurrency,
                global_memory_on=True,
            )
        else:
            from evaluation.planner_snapshot import load_or_create_planner_snapshot

            planned_rows = await load_or_create_planner_snapshot(
                rows,
                path=planner_snapshot_path,
                concurrency=concurrency,
                global_memory_on=True,
                retry_unknown_paid_calls=retry_unknown_paid_calls,
            )

    true_positive = 0
    true_negative = 0
    false_positive = 0
    false_negative = 0
    triggered_with_intents = 0
    plan_call_failures = 0
    planner_fallbacks = 0
    multi_intent_samples = 0
    multi_intent_planned = 0
    single_intent_overdecomposed = 0
    single_intent_predicted = 0
    exact_intent_count = 0
    intent_count_labeled_samples = 0
    unlabeled_predicted_samples = 0
    unlabeled_multi_intent = 0
    latencies: list[float] = []
    details: list[dict[str, Any]] = []

    for idx, (row, planned) in enumerate(zip(rows, planned_rows), start=1):
        latencies.append(planned.latency_ms / 1000)
        if planned.error is not None:
            plan_call_failures += 1
            logger.warning(
                "[L3 %d/%d] plan_query failed: %s",
                idx,
                len(rows),
                planned.error,
            )
            continue
        plan = planned.plan
        assert plan is not None

        expected = row.get("expected_planner_retrieval", True) is not False
        predicted = bool(plan.needs_knowledge_retrieval)
        planner_fallbacks += int(plan.planner_failed)
        if expected and predicted:
            true_positive += 1
        elif expected:
            false_negative += 1
        elif predicted:
            false_positive += 1
        else:
            true_negative += 1
        if predicted and plan.intents:
            triggered_with_intents += 1
        expected_intent_count = row.get("expected_intent_count")
        if expected_intent_count is not None:
            expected_intent_count = int(expected_intent_count)
            intent_count_labeled_samples += 1
            if expected_intent_count > 1:
                multi_intent_samples += 1
                multi_intent_planned += int(len(plan.intents) >= expected_intent_count)
            elif expected_intent_count == 1 and predicted:
                single_intent_predicted += 1
                single_intent_overdecomposed += int(len(plan.intents) > 1)
            exact_intent_count += int(len(plan.intents) == expected_intent_count)
        elif predicted:
            unlabeled_predicted_samples += 1
            unlabeled_multi_intent += int(len(plan.intents) > 1)
        details.append(
            {
                "id": row.get("id", ""),
                "expected_retrieval": expected,
                "predicted_retrieval": predicted,
                "planner_failed": plan.planner_failed,
                "expected_intent_count": expected_intent_count,
                "intents": [intent.model_dump() for intent in plan.intents],
                "intent_count": len(plan.intents),
            }
        )

        logger.info(
            "[L3 %d/%d] needs_knowledge=%s first_intent=%r",
            idx,
            len(rows),
            plan.needs_knowledge_retrieval,
            plan.intents[0].query[:40] if plan.intents else "",
        )

    succeeded = len(rows) - plan_call_failures
    predicted_positive = true_positive + false_positive
    actual_positive = true_positive + false_negative
    actual_negative = true_negative + false_positive
    summary = {
        "samples": len(rows),
        "succeeded": succeeded,
        "planner_concurrency": concurrency,
        "planner_latency_seconds": {
            "mean": round(sum(latencies) / len(latencies), 4),
            "p50": round(_percentile(latencies, 50), 4),
            "p95": round(_percentile(latencies, 95), 4),
        },
        "plan_call_failures": plan_call_failures,
        "planner_fallbacks": planner_fallbacks,
        "confusion_matrix": {
            "true_positive": true_positive,
            "true_negative": true_negative,
            "false_positive": false_positive,
            "false_negative": false_negative,
        },
        "routing_accuracy": round((true_positive + true_negative) / succeeded, 4)
        if succeeded
        else None,
        "retrieval_recall": round(true_positive / actual_positive, 4)
        if actual_positive
        else None,
        "retrieval_precision": round(true_positive / predicted_positive, 4)
        if predicted_positive
        else None,
        "no_retrieval_specificity": round(true_negative / actual_negative, 4)
        if actual_negative
        else None,
        "intent_populated_rate": (
            round(triggered_with_intents / predicted_positive, 4)
            if predicted_positive
            else None
        ),
        "intent_count_labeled_samples": intent_count_labeled_samples,
        "intent_count_accuracy": round(
            exact_intent_count / intent_count_labeled_samples, 4
        )
        if intent_count_labeled_samples
        else None,
        "multi_intent_planning_rate": (
            round(multi_intent_planned / multi_intent_samples, 4)
            if multi_intent_samples
            else None
        ),
        "single_intent_overdecomposition_rate": (
            round(single_intent_overdecomposed / single_intent_predicted, 4)
            if single_intent_predicted
            else None
        ),
        "unlabeled_multi_intent_rate": (
            round(unlabeled_multi_intent / unlabeled_predicted_samples, 4)
            if unlabeled_predicted_samples
            else None
        ),
        "per_sample_details": details,
    }
    if planner_snapshot_path is not None:
        from evaluation.planner_snapshot import (
            planner_attempt_metrics,
            planner_results_sha256,
        )

        summary["planner_results_sha256"] = planner_results_sha256(
            rows,
            planned_rows,
        )
        summary["planner_reliability"] = planner_attempt_metrics(
            planner_snapshot_path,
            rows,
            global_memory_on=True,
        )
    return summary


# ── Bootstrap helper shared by CLI + pytest ────────────────────────────


def prepare_runtime() -> None:
    """One-time runtime bootstrap.

    Called by both the CLI and the pytest session fixture so the
    evaluation environment matches what the production backend sees:

      1. ``prepare_hf_runtime`` — set HF_HOME, clear dead proxy env,
         create cache dirs.
      2. ``init_rag_settings``  — register the LlamaIndex embedding model.
         Answer generation and planning resolve their LLMs explicitly.
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
