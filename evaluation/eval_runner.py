"""CLI entry point for the RAG evaluation suite.

Usage::

    # Run all three layers
    python -m evaluation.eval_runner --all

    # Run a specific layer
    python -m evaluation.eval_runner --layer retrieval
    python -m evaluation.eval_runner --layer generation
    python -m evaluation.eval_runner --layer trajectory

    # Limit dataset rows + write a report under data/evaluation/reports/
    python -m evaluation.eval_runner --layer retrieval --limit 10 --report

    # Random-sample N rows instead of taking the first N
    python -m evaluation.eval_runner --layer generation --sample 20 --report

The actual evaluation logic lives in ``evaluation.runners`` so the
pytest suite (``test_*.py``) can call the same code paths via fixtures.
This module is just argparse + dispatch + pretty-printing.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import random
import sys
import time
from pathlib import Path
from typing import Any

# Fix Windows console encoding for the Chinese rows in the dataset.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Make ``backend/app/...`` importable without an editable install.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Offline benchmarks can create hundreds of traces in minutes. Keep them local;
# the generated JSON report is the evaluation system of record.
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"

from app.core.config import settings  # noqa: E402
from evaluation.runners import (  # noqa: E402
    DEFAULT_PLANNER_CONCURRENCY,
    RAG_DATASET_PATH,
    filter_by_layer,
    load_dataset,
    prepare_runtime,
    run_generation,
    run_retrieval,
    run_trajectory,
)

LAYERS = ("retrieval", "generation", "trajectory")


def _print_layer_summary(layer: str, result: dict[str, Any]) -> None:
    """Pretty-print one layer's summary (skip the per-sample detail list)."""
    printable = {k: v for k, v in result.items() if k != "per_sample_details"}
    print(json.dumps(printable, ensure_ascii=False, indent=2))


def _sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _json_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def select_generation_evaluation_rows(
    rows: list[dict[str, Any]],
    *,
    judge_limit: int,
) -> list[dict[str, Any]]:
    from evaluation.ragas_runner import select_formal_rows

    formal_rows = select_formal_rows(rows)
    if judge_limit == 1:
        return formal_rows[:1]
    if judge_limit != 50:
        raise ValueError("fixed RAGAS profile must judge 1 or 50 rows")
    return formal_rows + [
        row
        for row in rows
        if row.get("expected_retrieval") is False and row.get("split") == "test"
    ]


async def _run_layers_unlocked(
    layers: list[str],
    rows: list[dict[str, Any]],
    *,
    judge_limit: int | None,
    retrieval_query_mode: str,
    planner_concurrency: int,
    planner_snapshot: Path,
    retry_ragas_errors: bool,
    retry_unknown_paid_calls: bool,
) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for layer in layers:
        print("=" * 60)
        print(f"  Layer: {layer.upper()}")
        print("=" * 60)
        start = time.perf_counter()
        layer_rows = filter_by_layer(rows, layer)
        if not layer_rows:
            print(f"  (no {layer}-layer rows in dataset; skipping)\n")
            continue
        if layer == "generation":
            if judge_limit:
                from evaluation.planner_snapshot import DEFAULT_GLOBAL_MEMORY_SNAPSHOT

                layer_rows = select_generation_evaluation_rows(
                    layer_rows,
                    judge_limit=judge_limit,
                )
            else:
                from evaluation.planner_snapshot import DEFAULT_GLOBAL_MEMORY_SNAPSHOT
            result = await run_generation(
                layer_rows,
                judge_limit=judge_limit,
                retry_ragas_errors=retry_ragas_errors,
                retry_unknown_paid_calls=retry_unknown_paid_calls,
                planner_concurrency=planner_concurrency,
                planner_snapshot_path=DEFAULT_GLOBAL_MEMORY_SNAPSHOT,
            )
        elif layer == "retrieval":
            planned_rows = None
            if retrieval_query_mode == "planned":
                from evaluation.planner_snapshot import (
                    load_or_create_planner_snapshot,
                    planner_attempt_metrics,
                    planner_results_sha256,
                )

                planned_rows = await load_or_create_planner_snapshot(
                    layer_rows,
                    path=planner_snapshot,
                    concurrency=planner_concurrency,
                    retry_unknown_paid_calls=retry_unknown_paid_calls,
                )
            result = await run_retrieval(
                layer_rows,
                query_mode=retrieval_query_mode,
                planned_rows=planned_rows,
                planner_concurrency=planner_concurrency,
                verify_tenant_isolation=True,
            )
            if planned_rows is not None:
                result["planner_results_sha256"] = planner_results_sha256(
                    layer_rows,
                    planned_rows,
                )
                result["planner_reliability"] = planner_attempt_metrics(
                    planner_snapshot,
                    layer_rows,
                    global_memory_on=False,
                )
        else:
            from evaluation.planner_snapshot import DEFAULT_GLOBAL_MEMORY_SNAPSHOT

            result = await run_trajectory(
                layer_rows,
                concurrency=planner_concurrency,
                planner_snapshot_path=DEFAULT_GLOBAL_MEMORY_SNAPSHOT,
                retry_unknown_paid_calls=retry_unknown_paid_calls,
            )
        results[layer] = result
        elapsed = time.perf_counter() - start
        print(f"\n  Completed in {elapsed:.1f}s")
        _print_layer_summary(layer, result)
        print()
    return results


async def _run_layers(
    layers: list[str],
    rows: list[dict[str, Any]],
    **kwargs: Any,
) -> dict[str, dict[str, Any]]:
    if not any(layer in {"retrieval", "generation"} for layer in layers):
        return await _run_layers_unlocked(layers, rows, **kwargs)

    from evaluation.index_provenance import validate_evaluation_index
    from evaluation.workflow_lock import evaluation_index_lock

    with evaluation_index_lock():
        before = validate_evaluation_index()
        results = await _run_layers_unlocked(layers, rows, **kwargs)
        after = validate_evaluation_index()
        if after["fingerprint"] != before["fingerprint"]:
            raise RuntimeError(
                "Evaluation index changed while the benchmark was running"
            )
        for layer in {"retrieval", "generation"}.intersection(results):
            results[layer]["index_provenance"] = after
        return results


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Interview Copilot RAG Evaluation Suite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all evaluation layers",
    )
    parser.add_argument(
        "--layer",
        choices=LAYERS,
        help="Run a specific layer",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Take the first N rows of the dataset",
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=None,
        help="JSONL dataset path (default: evaluation/rag_dataset.jsonl)",
    )
    parser.add_argument(
        "--retrieval-query-mode",
        choices=("direct", "planned"),
        default="direct",
        help="direct isolates retrieval without LLM cost; planned uses the production planner.",
    )
    parser.add_argument(
        "--ragas-profile",
        choices=("none", "check", "formal"),
        default="none",
        help="RAGAS profile: none=0, check=1 compatibility row, formal=50 fixed rows.",
    )
    parser.add_argument(
        "--planner-concurrency",
        type=int,
        default=DEFAULT_PLANNER_CONCURRENCY,
        help=(
            "Maximum concurrent planner requests "
            f"(default {DEFAULT_PLANNER_CONCURRENCY})."
        ),
    )
    parser.add_argument(
        "--planner-snapshot",
        type=Path,
        default=PROJECT_ROOT / "data" / "evaluation" / "planner" / "retrieval.json",
        help="Validated immutable planner snapshot shared by retrieval runs.",
    )
    parser.add_argument(
        "--profile",
        type=Path,
        default=None,
        help="Completed CUDA release report that freezes the RAG profile.",
    )
    parser.add_argument(
        "--retry-ragas-errors",
        action="store_true",
        help="Retry only failed RAGAS sample/metric checkpoint entries.",
    )
    parser.add_argument(
        "--retry-unknown-paid-calls",
        action="store_true",
        help="Explicitly retry requests left in an unknown paid state after a crash.",
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=None,
        help="Randomly sample N rows (after layer filtering). Mutually "
        "exclusive with --limit.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="Random seed for --sample (default 0, reproducible).",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Write JSON + Markdown report under data/evaluation/reports/",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="count",
        default=0,
        help="-v for INFO logs, -vv for DEBUG",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    if not args.all and not args.layer:
        # No-arg invocation prints help instead of silently doing nothing.
        argparse.ArgumentParser(description=__doc__).print_help()
        sys.exit(0)
    if args.limit and args.sample:
        print("ERROR: --limit and --sample are mutually exclusive.", file=sys.stderr)
        sys.exit(2)
    if args.ragas_profile != "none" and (args.limit or args.sample):
        print(
            "ERROR: fixed RAGAS profiles cannot be combined with --limit or --sample.",
            file=sys.stderr,
        )
        sys.exit(2)
    if args.planner_concurrency < 1:
        print("ERROR: --planner-concurrency must be at least 1.", file=sys.stderr)
        sys.exit(2)
    logging.basicConfig(
        level=logging.DEBUG
        if args.verbose >= 2
        else logging.INFO
        if args.verbose >= 1
        else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    rows = load_dataset(limit=args.limit, path=args.dataset)
    if args.sample:
        random.seed(args.seed)
        rows = random.sample(rows, min(args.sample, len(rows)))
    print(f"Loaded {len(rows)} dataset rows.\n")

    layers = list(LAYERS) if args.all else [args.layer]
    if args.ragas_profile != "none" and layers != ["generation"]:
        print(
            "ERROR: --ragas-profile requires --layer generation only.",
            file=sys.stderr,
        )
        sys.exit(2)
    if args.ragas_profile != "none" and not args.report:
        print(
            "ERROR: --ragas-profile check/formal requires --report.",
            file=sys.stderr,
        )
        sys.exit(2)
    if args.ragas_profile != "none" and args.profile is None:
        print(
            "ERROR: --ragas-profile check/formal requires --profile from the "
            "completed CUDA release validation.",
            file=sys.stderr,
        )
        sys.exit(2)
    if (
        args.ragas_profile == "none"
        and "generation" in layers
        and not (args.limit or args.sample)
    ):
        print(
            "ERROR: live generation without RAGAS requires --limit or --sample; "
            "this prevents an accidental full-dataset paid run.",
            file=sys.stderr,
        )
        sys.exit(2)
    if args.retry_ragas_errors and args.ragas_profile == "none":
        print(
            "ERROR: --retry-ragas-errors requires --ragas-profile check or formal.",
            file=sys.stderr,
        )
        sys.exit(2)
    dataset_path = (args.dataset or RAG_DATASET_PATH).resolve()
    release_profile_sha256 = None
    release_profile_selection_device = None
    release_run_fingerprint = None
    if args.profile is not None:
        from evaluation.rag_release import (
            apply_release_profile,
            load_release_profile,
        )

        profile, release_profile_sha256, release_profile_selection_device = (
            load_release_profile(args.profile.resolve())
        )
        release_payload = json.loads(args.profile.resolve().read_text(encoding="utf-8"))
        release_run_fingerprint = release_payload.get("run_fingerprint")
        release_dataset_sha = (release_payload.get("run_identity") or {}).get(
            "dataset_sha256"
        )
        if release_dataset_sha != _sha256(dataset_path):
            print(
                "ERROR: release profile belongs to a different RAG dataset.",
                file=sys.stderr,
            )
            sys.exit(2)
        apply_release_profile(settings, profile)
        from evaluation.index_provenance import (
            validate_evaluation_index,
            validate_manifest_files,
        )

        release_identity = release_payload.get("run_identity") or {}
        current_corpus = validate_manifest_files()
        if release_identity.get("corpus_fingerprint") != current_corpus.get(
            "fingerprint"
        ):
            print(
                "ERROR: release profile belongs to different corpus bytes.",
                file=sys.stderr,
            )
            sys.exit(2)
        current_index = validate_evaluation_index()
        reported_index = release_payload.get("index_provenance") or {}
        if reported_index.get("fingerprint") != current_index.get("fingerprint"):
            print(
                "ERROR: release profile belongs to a different evaluation index.",
                file=sys.stderr,
            )
            sys.exit(2)
    judge_limit = {"none": 0, "check": 1, "formal": 50}[args.ragas_profile]
    if judge_limit:
        from evaluation.ragas_runner import formal_sample_manifest

        expected_sha = formal_sample_manifest()["dataset_sha256"]
        actual_sha = _sha256(dataset_path)
        if actual_sha != expected_sha:
            print(
                "ERROR: the pinned RAGAS sample belongs to a different dataset "
                f"({expected_sha}); current SHA-256 is {actual_sha}.",
                file=sys.stderr,
            )
            sys.exit(2)
        from app.rag.policy import resolve_rag_device

        if resolve_rag_device() != "cuda":
            print(
                "ERROR: check/formal release evaluation requires CUDA.",
                file=sys.stderr,
            )
            sys.exit(2)
    prepare_runtime()
    results = asyncio.run(
        _run_layers(
            layers,
            rows,
            judge_limit=judge_limit,
            retrieval_query_mode=args.retrieval_query_mode,
            planner_concurrency=args.planner_concurrency,
            planner_snapshot=args.planner_snapshot.resolve(),
            retry_ragas_errors=args.retry_ragas_errors,
            retry_unknown_paid_calls=args.retry_unknown_paid_calls,
        )
    )
    index_provenance = next(
        (
            result.get("index_provenance")
            for result in results.values()
            if result.get("index_provenance") is not None
        ),
        None,
    )

    if args.report:
        from evaluation.report import generate_report, hardware_metadata
        from app.rag.policy import resolve_rag_device
        from evaluation.rag_release import evaluation_code_sha256
        from evaluation.ragas_runner import _generation_contract_sha256
        from evaluation.planner_snapshot import (
            DEFAULT_GLOBAL_MEMORY_SNAPSHOT,
        )

        rag_profile = {
            "min_score": settings.RAG_MIN_SCORE,
            "score_margin": settings.RAG_SCORE_MARGIN,
            "chunk_tokens": settings.RAG_CHUNK_TOKENS,
            "chunk_overlap": settings.RAG_CHUNK_OVERLAP,
            "candidate_count": settings.RAG_CANDIDATE_COUNT,
            "final_count": settings.RAG_FINAL_COUNT,
            "embedding_provider": settings.EMBEDDING_PROVIDER,
            "embedding_model": settings.EMBEDDING_MODEL,
            "reranker_provider": settings.RERANKER_PROVIDER,
            "reranker_model": settings.RERANKER_MODEL,
        }
        snapshot_paths = {
            "retrieval": args.planner_snapshot.resolve(),
            "generation": DEFAULT_GLOBAL_MEMORY_SNAPSHOT.resolve(),
            "trajectory": DEFAULT_GLOBAL_MEMORY_SNAPSHOT.resolve(),
        }
        planner_snapshots = {
            layer: {
                "path": str(snapshot_paths[layer]),
                "sha256": _sha256(snapshot_paths[layer]),
                "planner_results_sha256": results.get(layer, {}).get(
                    "planner_results_sha256"
                ),
            }
            for layer in layers
            if layer in snapshot_paths
        }
        report_dir = generate_report(
            retrieval=results.get("retrieval"),
            generation=results.get("generation"),
            trajectory=results.get("trajectory"),
            metadata={
                "dataset_path": str(dataset_path),
                "dataset_sha256": _sha256(dataset_path),
                "corpus_manifest_sha256": _sha256(
                    PROJECT_ROOT / "evaluation" / "corpus_manifest.json"
                ),
                "loaded_rows": len(rows),
                "layers": layers,
                "sample_seed": args.seed if args.sample else None,
                "ragas_profile": args.ragas_profile,
                "ragas_sample_size": judge_limit,
                "retrieval_query_mode": args.retrieval_query_mode,
                "planner_concurrency": args.planner_concurrency,
                "planner_snapshots": planner_snapshots,
                "rag_min_score": settings.RAG_MIN_SCORE,
                "rag_score_margin": settings.RAG_SCORE_MARGIN,
                "rag_chunk_tokens": settings.RAG_CHUNK_TOKENS,
                "rag_chunk_overlap": settings.RAG_CHUNK_OVERLAP,
                "rag_candidate_count": settings.RAG_CANDIDATE_COUNT,
                "rag_final_count": settings.RAG_FINAL_COUNT,
                "rag_profile_sha256": _json_sha256(rag_profile),
                "release_profile_path": str(args.profile.resolve())
                if args.profile
                else None,
                "release_profile_sha256": release_profile_sha256,
                "release_profile_selection_device": (release_profile_selection_device),
                "release_run_fingerprint": release_run_fingerprint,
                "evaluation_code_sha256": evaluation_code_sha256(),
                "generation_contract_sha256": (
                    _generation_contract_sha256() if "generation" in results else None
                ),
                "ragas_evaluation_contract": results.get("generation", {}).get(
                    "ragas_evaluation_contract"
                ),
                "rag_device": resolve_rag_device(),
                "embedding_provider": settings.EMBEDDING_PROVIDER,
                "embedding_model": settings.EMBEDDING_MODEL,
                "reranker_provider": settings.RERANKER_PROVIDER,
                "reranker_model": settings.RERANKER_MODEL,
                "internal_model": (
                    f"{settings.INTERNAL_LLM_PROVIDER}/{settings.INTERNAL_LLM_MODEL}"
                ),
                "index_provenance": index_provenance,
                "hardware": hardware_metadata(),
            },
        )
        print(f"Report saved to: {report_dir}")


if __name__ == "__main__":
    main()
