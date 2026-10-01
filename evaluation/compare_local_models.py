"""Calibration-only production BGE comparison with measured retrieval stages.

Reuse the frozen planner snapshot; never call the planner or open the held-out split.
Run only against an isolated evaluation database. --rebuild replaces the selected
user's evaluation corpus using the production ingestion path. --reembed-existing
holds all existing passages fixed to isolate model changes from parsing/chunking.
"""

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=["bge"], default="bge")
    parser.add_argument("--rerank-input-tokens", type=int, default=512)
    parser.add_argument("--user", default="release_eval_20260923")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument(
        "--reembed-existing",
        action="store_true",
        help="Freeze canonical chunks; replace only their embedding vectors",
    )
    parser.add_argument("--planner-snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.rebuild and args.reembed_existing:
        parser.error("Choose either full reingestion or frozen-chunk reembedding")
    from app.core.config import settings

    settings.RAG_DEVICE = "cuda"
    settings.PARSER_PROVIDER = "docling"
    settings.EMBEDDING_PROVIDER = settings.RERANKER_PROVIDER = "local"
    settings.EMBEDDING_DIM = 1024
    settings.RAG_RERANK_INPUT_TOKENS = args.rerank_input_tokens
    settings.RAG_CHUNK_TOKENS = 384
    settings.RAG_CHUNK_OVERLAP = 64
    settings.RAG_CANDIDATE_COUNT = 20
    settings.RAG_FINAL_COUNT = 3
    settings.EMBEDDING_MODEL = "BAAI/bge-m3"
    settings.RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"
    if not settings.DATABASE_URL.rsplit("/", 1)[-1].startswith("rag_compare"):
        raise ValueError("This diagnostic must use an isolated rag_compare database")

    from evaluation.runners import (
        prepare_runtime,
        load_dataset,
        filter_by_layer,
        run_retrieval,
        PlannerEvaluationResult,
        validate_evidence_alignment,
    )
    from evaluation.metrics import aggregate_scores
    from evaluation.rag_release import _current_runtime_contract
    from evaluation.retrieval_gates import retrieval_release_gates
    from evaluation.report import hardware_metadata
    from app.conversation.query_planner import QueryPlan
    from app.rag.retrieval.pipeline import KnowledgeRetrievalPipeline
    from app.rag.retrieval import candidates
    from app.rag import hybrid_index
    from app.rag.application.service import rag_service
    from app.core.runtime_resources import close_current_resources

    dataset = ROOT / "evaluation/rag_dataset.jsonl"
    rows = [
        {**r, "user_id": args.user}
        for r in filter_by_layer(load_dataset(path=dataset), "retrieval")
        if r.get("split") == "calibration"
    ]
    snapshot = json.loads(args.planner_snapshot.read_text(encoding="utf-8"))
    plans = {p["id"]: p["plan"] for p in snapshot["plans"]}
    missing = [r["id"] for r in rows if r["id"] not in plans]
    if missing:
        raise ValueError(
            f"Frozen planner snapshot is missing calibration rows: {missing}"
        )
    planned = [
        PlannerEvaluationResult(
            plan=QueryPlan(**plans[r["id"]]), error=None, latency_ms=0
        )
        for r in rows
    ]
    print("loading", args.profile, "calibration rows", len(rows), flush=True)
    prepare_runtime()

    async def run():
        if args.reembed_existing:
            from app.db.database import SessionLocal
            from app.models.knowledge import KnowledgeDocument
            from app.models.user import User
            from app.rag.index.knowledge import reindex_document
            from evaluation.isolation_probe import ISOLATION_USER

            with SessionLocal() as db:
                ids = [
                    row[0]
                    for row in db.query(KnowledgeDocument.id)
                    .join(User, User.id == KnowledgeDocument.user_id)
                    .filter(User.username.in_([args.user, ISOLATION_USER]))
                    .order_by(KnowledgeDocument.id)
                    .all()
                ]
            for i, document_id in enumerate(ids, 1):
                count = reindex_document(document_id)
                print("reembedded frozen document", i, len(ids), count, flush=True)
        if args.rebuild:
            from evaluation.prepare_corpus import (
                _ensure_user,
                _manifest_paths,
                _reset_user_corpus,
                _run,
                _prepare_isolation_probe,
            )

            user_pk = _ensure_user(args.user)
            _reset_user_corpus(user_pk)
            await _run(_manifest_paths(ROOT / "data/evaluation/corpus"), user_pk)
            await _prepare_isolation_probe(reset=True)
        alignment = validate_evidence_alignment(rows)
        print("evidence alignment", alignment, flush=True)
        for row_plan in planned[:3]:
            await rag_service.retrieve(
                intents=row_plan.plan.intents, user_id=args.user, min_score=0.0
            )
        durations = defaultdict(list)
        pipeline_timings = []
        original_retrieve = KnowledgeRetrievalPipeline.retrieve
        original_embedding = candidates._query_embedding

        async def retrieve(self, **kwargs):
            result = await original_retrieve(self, **kwargs)
            pipeline_timings.append(result.diagnostics.get("timings_ms", {}))
            if len(pipeline_timings) % 20 == 0:
                print("retrieval", len(pipeline_timings), flush=True)
            return result

        async def embedding(query):
            start = time.perf_counter()
            try:
                return await original_embedding(query)
            finally:
                durations["embedding_call_wall_ms"].append(
                    (time.perf_counter() - start) * 1000
                )

        def timed(name, fn):
            def call(*a, **kw):
                start = time.perf_counter()
                try:
                    return fn(*a, **kw)
                finally:
                    durations[name].append((time.perf_counter() - start) * 1000)

            return call

        with (
            patch.object(KnowledgeRetrievalPipeline, "retrieve", retrieve),
            patch.object(candidates, "_query_embedding", embedding),
            patch.object(
                hybrid_index,
                "dense_search",
                timed("dense_sql_call_ms", hybrid_index.dense_search),
            ),
            patch.object(
                hybrid_index,
                "sparse_search",
                timed("sparse_sql_call_ms", hybrid_index.sparse_search),
            ),
        ):
            result = await run_retrieval(
                rows,
                query_mode="planned",
                planned_rows=planned,
                verify_tenant_isolation=True,
            )
        stages = defaultdict(list)
        for values in pipeline_timings[: len(rows)]:
            for key, value in values.items():
                stages[key].append(value)
        payload = {
            "profile": args.profile,
            "index_mode": "frozen canonical chunks"
            if args.reembed_existing
            else "full reingestion"
            if args.rebuild
            else "existing baseline",
            "release_ready": False,
            "scope": "calibration comparison only; no held-out evaluation; planner replay excluded from latency",
            "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
            "planner_sha256": hashlib.sha256(
                args.planner_snapshot.read_bytes()
            ).hexdigest(),
            "runtime": _current_runtime_contract(),
            "selection": {
                "threshold": settings.RAG_MIN_SCORE,
                "margin": settings.RAG_SCORE_MARGIN,
                "candidate_count": settings.RAG_CANDIDATE_COUNT,
                "final_count": settings.RAG_FINAL_COUNT,
            },
            "hardware": hardware_metadata(),
            "versions": {
                key: importlib.metadata.version(key)
                for key in [
                    "torch",
                    "transformers",
                    "sentence-transformers",
                    "llama-index-core",
                ]
            },
            "stage_ms": {
                key: aggregate_scores(values) for key, values in stages.items()
            },
            "operation_ms": {
                key: aggregate_scores(values) for key, values in durations.items()
            },
            "operation_counts": {key: len(values) for key, values in durations.items()},
            "alignment": alignment,
            "deployed_gates": retrieval_release_gates(
                result, threshold_mode="deployed"
            ),
            "calibrated_gates": retrieval_release_gates(
                result, threshold_mode="calibrated"
            ),
            "metrics": result,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print("saved", args.output, flush=True)
        await close_current_resources()

    asyncio.run(run())


if __name__ == "__main__":
    main()
