"""Build and validate the one fixed Community RAG release profile on CUDA."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

FIXED_PROFILE = {
    "chunk_tokens": 384,
    "chunk_overlap": 64,
    "candidate_count": 20,
    "final_count": 3,
}
DEFAULT_PLANNER_CONCURRENCY = 16
CAMPAIGN_LEDGER_ROOT = PROJECT_ROOT / "data" / "evaluation" / "release" / "campaigns"


def _structural_profile(profile: dict[str, Any]) -> dict[str, int]:
    return {key: int(profile[key]) for key in FIXED_PROFILE}


def profile_sha256(profile: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(profile, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _current_runtime_contract() -> dict[str, Any]:
    from app.core.config import settings

    return {
        "parser_provider": settings.PARSER_PROVIDER,
        "ocr_enabled": settings.RAG_OCR_ENABLED,
        "embedding_provider": settings.EMBEDDING_PROVIDER,
        "embedding_model": settings.EMBEDDING_MODEL,
        "embedding_dim": settings.EMBEDDING_DIM,
        "reranker_provider": settings.RERANKER_PROVIDER,
        "reranker_model": settings.RERANKER_MODEL,
        "rerank_input_tokens": settings.RAG_RERANK_INPUT_TOKENS,
        "query_token_reserve": settings.RAG_QUERY_TOKEN_RESERVE,
        "max_intents": settings.RAG_MAX_INTENTS,
        "milvus_uri_sha256": hashlib.sha256(
            settings.MILVUS_URI.encode("utf-8")
        ).hexdigest(),
        "milvus_collection": settings.MILVUS_COLLECTION,
        "milvus_similarity_metric": settings.MILVUS_SIMILARITY_METRIC,
        "milvus_dense_index_type": settings.MILVUS_DENSE_INDEX_TYPE,
        "milvus_hnsw_m": settings.MILVUS_HNSW_M,
        "milvus_hnsw_ef_construction": settings.MILVUS_HNSW_EF_CONSTRUCTION,
        "milvus_hnsw_ef_search": settings.MILVUS_HNSW_EF_SEARCH,
    }


def load_release_profile(path: Path) -> tuple[dict[str, Any], str, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("release_ready") is not True or payload.get("status") != "completed":
        raise ValueError("evaluation requires a completed, release-ready profile")
    profile = payload.get("selected_profile")
    if not isinstance(profile, dict):
        raise ValueError("release report has no selected_profile")
    if _structural_profile(profile) != FIXED_PROFILE:
        raise ValueError("release report does not use the fixed Community profile")
    if "min_score" not in profile or "score_margin" not in profile:
        raise ValueError("release report has no calibrated evidence gate")
    if not 0.0 <= float(profile["min_score"]) <= 1.0:
        raise ValueError("release min_score must be between 0 and 1")
    margin = profile["score_margin"]
    if margin is not None and not 0.0 <= float(margin) <= 1.0:
        raise ValueError("release score_margin must be null or between 0 and 1")
    fingerprint = profile_sha256(profile)
    if payload.get("selected_profile_sha256") != fingerprint:
        raise ValueError("selected profile fingerprint does not match the report")
    selection_device = str(payload.get("device") or "")
    if selection_device != "cuda":
        raise ValueError("the release profile must be validated on CUDA")
    identity = payload.get("run_identity") or {}
    if identity.get("evaluation_code_sha256") != evaluation_code_sha256():
        raise ValueError("release report belongs to a different evaluation contract")
    if identity.get("runtime_contract") != _current_runtime_contract():
        raise ValueError("release report belongs to a different RAG runtime contract")
    return profile, fingerprint, selection_device


def apply_release_profile(settings: Any, profile: dict[str, Any]) -> None:
    settings.RAG_CHUNK_TOKENS = int(profile["chunk_tokens"])
    settings.RAG_CHUNK_OVERLAP = int(profile["chunk_overlap"])
    settings.RAG_CANDIDATE_COUNT = int(profile["candidate_count"])
    settings.RAG_FINAL_COUNT = int(profile.get("final_count") or 3)
    if "min_score" in profile:
        settings.RAG_MIN_SCORE = float(profile["min_score"])
    if "score_margin" in profile:
        settings.RAG_SCORE_MARGIN = (
            None
            if profile.get("score_margin") is None
            else float(profile["score_margin"])
        )


def evaluation_code_sha256() -> str:
    paths = [
        Path(__file__),
        *sorted((PROJECT_ROOT / "evaluation").glob("*.py")),
        *sorted((BACKEND_ROOT / "app" / "rag").rglob("*.py")),
        BACKEND_ROOT / "app" / "conversation" / "query_planner.py",
        BACKEND_ROOT / "app" / "core" / "config.py",
        BACKEND_ROOT / "app" / "core" / "llm_client_factory.py",
        BACKEND_ROOT / "app" / "prompts" / "chat.py",
    ]
    digest = hashlib.sha256()
    for path in dict.fromkeys(paths):
        digest.update(str(path.relative_to(PROJECT_ROOT)).encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _dependency_versions() -> dict[str, str]:
    names = (
        "docling",
        "llama-index-core",
        "pymilvus",
        "pymupdf",
        "sentence-transformers",
        "torch",
        "transformers",
    )
    versions: dict[str, str] = {}
    for name in names:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "not-installed"
    return versions


def _compact(metrics: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in metrics.items() if key != "per_sample_details"}


def _retrieval_failures(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        detail
        for detail in metrics.get("per_sample_details") or []
        if detail.get("expected_retrieval")
        and not detail.get("reranked_passage_hit_at_3")
    ]


def _save(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _identity_fingerprint(identity: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _heldout_ledger_path(campaign_fingerprint: str) -> Path:
    return CAMPAIGN_LEDGER_ROOT / f"{campaign_fingerprint}.json"


def _claim_heldout_once(
    *,
    campaign_fingerprint: str,
    output: Path,
    selected_profile_sha256: str,
) -> Path:
    """Irreversibly open one held-out run for an evaluation campaign."""
    ledger = _heldout_ledger_path(campaign_fingerprint)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": 1,
        "campaign_fingerprint": campaign_fingerprint,
        "status": "heldout_running",
        "opened_at": datetime.now(UTC).isoformat(),
        "output": str(output),
        "selected_profile_sha256": selected_profile_sha256,
    }
    try:
        with ledger.open("x", encoding="utf-8") as handle:
            json.dump(record, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise RuntimeError(
            "The held-out split was already opened for this evaluation campaign"
        ) from exc
    return ledger


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    from app.core.config import settings
    from app.rag.policy import resolve_rag_device
    from evaluation.index_provenance import (
        validate_evaluation_index,
        validate_manifest_files,
    )
    from evaluation.planner_snapshot import (
        load_or_create_planner_snapshot,
        planner_attempt_metrics,
        planner_results_sha256,
    )
    from evaluation.prepare_corpus import (
        _ensure_user,
        _manifest_paths,
        _prepare_isolation_probe,
        _reset_user_corpus,
        _run as index_paths,
    )
    from evaluation.report import hardware_metadata
    from evaluation.retrieval_gates import retrieval_release_gates
    from evaluation.runners import (
        filter_by_layer,
        load_dataset,
        prepare_runtime,
        run_retrieval,
        validate_evidence_alignment,
    )
    from evaluation.validate_rag_dataset import validate_dataset

    settings.RAG_DEVICE = "cuda"
    settings.PARSER_PROVIDER = "docling"
    apply_release_profile(settings, FIXED_PROFILE)
    if resolve_rag_device() != "cuda":
        raise RuntimeError("The release benchmark requires an available CUDA device")

    dataset_validation = validate_dataset(
        args.dataset,
        PROJECT_ROOT / "evaluation" / "corpus_manifest.json",
        PROJECT_ROOT / "evaluation" / "ragas_formal_sample.json",
    )
    corpus = validate_manifest_files(args.source_dir)
    rows = filter_by_layer(load_dataset(path=args.dataset), "retrieval")
    calibration_rows = [row for row in rows if row.get("split") == "calibration"]
    test_rows = [row for row in rows if row.get("split") == "test"]
    prepare_runtime()
    user_pk = _ensure_user(args.user)
    base_identity = {
        "schema_version": 2,
        "device": "cuda",
        "dataset_sha256": hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
        "corpus_fingerprint": corpus["fingerprint"],
        "evaluation_code_sha256": evaluation_code_sha256(),
        "dependency_versions": _dependency_versions(),
        "hardware": hardware_metadata(),
        "target_user": args.user,
        "profile": FIXED_PROFILE,
        "runtime_contract": _current_runtime_contract(),
    }
    campaign_fingerprint = _identity_fingerprint(base_identity)
    if args.output.is_file():
        previous = json.loads(args.output.read_text(encoding="utf-8"))
        previous_identity = dict(previous.get("run_identity") or {})
        previous_identity.pop("planner_results_sha256", None)
        if previous_identity != base_identity:
            raise RuntimeError("Release output belongs to a different campaign")
        if previous.get("status") == "completed":
            return previous
        if previous.get("status") in {"failed", "heldout_running"}:
            raise RuntimeError(
                "This release campaign is terminal; use a new output path after "
                "fixing the cause"
            )
    if _heldout_ledger_path(campaign_fingerprint).exists():
        raise RuntimeError(
            "The held-out split was already opened for this evaluation campaign"
        )
    plans = await load_or_create_planner_snapshot(
        rows,
        path=args.planner_snapshot,
        concurrency=args.planner_concurrency,
        retry_unknown_paid_calls=args.retry_unknown_paid_calls,
    )
    plans_by_id = {str(row["id"]): plan for row, plan in zip(rows, plans)}
    calibration_plans = [plans_by_id[str(row["id"])] for row in calibration_rows]
    test_plans = [plans_by_id[str(row["id"])] for row in test_rows]
    planner_hash = planner_results_sha256(rows, plans)
    identity = {
        **base_identity,
        "planner_results_sha256": planner_hash,
    }
    fingerprint = _identity_fingerprint(identity)

    payload: dict[str, Any] = {
        "schema_version": 2,
        "status": "running",
        "started_at": datetime.now(UTC).isoformat(),
        "run_identity": identity,
        "run_fingerprint": fingerprint,
        "device": "cuda",
        "planner_concurrency": args.planner_concurrency,
        "planner_results_sha256": planner_hash,
        "planner_reliability": planner_attempt_metrics(
            args.planner_snapshot,
            rows,
            global_memory_on=False,
        ),
        "calibration_samples": len(calibration_rows),
        "test_samples": len(test_rows),
        "fixed_profile": FIXED_PROFILE,
        "dataset_validation": dataset_validation,
    }
    _save(payload, args.output)

    paths = _manifest_paths(args.source_dir)
    try:
        index = validate_evaluation_index(
            username=args.user,
            source_dir=args.source_dir,
        )
        index_rebuilt = False
    except ValueError:
        _reset_user_corpus(user_pk)
        await index_paths(paths, user_pk)
        index = validate_evaluation_index(
            username=args.user,
            source_dir=args.source_dir,
        )
        index_rebuilt = True
    await _prepare_isolation_probe(reset=True)
    try:
        evidence_alignment = validate_evidence_alignment(rows)
    except RuntimeError as exc:
        payload.update(
            status="failed",
            completed_at=datetime.now(UTC).isoformat(),
            failure_stage="evidence_alignment",
            failure=str(exc),
            index_provenance=index,
            index_rebuilt=index_rebuilt,
            release_ready=False,
        )
        _save(payload, args.output)
        raise
    payload.update(
        index_provenance=index,
        index_rebuilt=index_rebuilt,
        evidence_alignment=evidence_alignment,
    )
    _save(payload, args.output)

    warmup_rows = calibration_rows[:3]
    await run_retrieval(
        warmup_rows,
        query_mode="planned",
        planned_rows=calibration_plans[:3],
        planner_concurrency=args.planner_concurrency,
    )
    calibration_metrics = await run_retrieval(
        calibration_rows,
        query_mode="planned",
        planned_rows=calibration_plans,
        planner_concurrency=args.planner_concurrency,
        verify_tenant_isolation=True,
    )
    calibration_gates = retrieval_release_gates(
        calibration_metrics,
        threshold_mode="calibrated",
    )
    calibration = calibration_metrics.get("threshold_calibration") or {}
    threshold = calibration.get("recommended_threshold")
    margin = calibration.get("recommended_score_margin")
    if not all(calibration_gates.values()) or threshold is None:
        payload.update(
            status="failed",
            completed_at=datetime.now(UTC).isoformat(),
            calibration_metrics=_compact(calibration_metrics),
            calibration_failures=_retrieval_failures(calibration_metrics),
            calibration_quality_gates=calibration_gates,
            release_ready=False,
        )
        _save(payload, args.output)
        raise RuntimeError("The fixed profile failed calibration release gates")

    selected_profile = {
        **FIXED_PROFILE,
        "min_score": float(threshold),
        "score_margin": margin,
    }
    apply_release_profile(settings, selected_profile)
    selected_profile_fingerprint = profile_sha256(selected_profile)
    heldout_ledger = _claim_heldout_once(
        campaign_fingerprint=campaign_fingerprint,
        output=args.output,
        selected_profile_sha256=selected_profile_fingerprint,
    )
    payload.update(
        status="heldout_running",
        selected_profile=selected_profile,
        selected_profile_sha256=selected_profile_fingerprint,
        heldout_campaign_fingerprint=campaign_fingerprint,
        calibration_metrics=_compact(calibration_metrics),
        calibration_quality_gates=calibration_gates,
    )
    _save(payload, args.output)

    heldout_metrics = await run_retrieval(
        test_rows,
        query_mode="planned",
        planned_rows=test_plans,
        planner_concurrency=args.planner_concurrency,
        verify_tenant_isolation=True,
    )
    heldout_gates = retrieval_release_gates(
        heldout_metrics,
        threshold_mode="deployed",
    )
    payload.update(
        status="completed",
        completed_at=datetime.now(UTC).isoformat(),
        held_out_metrics=_compact(heldout_metrics),
        held_out_quality_gates=heldout_gates,
        release_ready=all(heldout_gates.values()),
    )
    _save(payload, args.output)
    ledger_payload = json.loads(heldout_ledger.read_text(encoding="utf-8"))
    ledger_payload.update(
        status="completed",
        completed_at=payload["completed_at"],
        release_ready=payload["release_ready"],
    )
    _save(ledger_payload, heldout_ledger)
    return payload


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=PROJECT_ROOT / "evaluation" / "rag_dataset.jsonl",
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "evaluation" / "corpus",
    )
    parser.add_argument(
        "--planner-snapshot",
        type=Path,
        default=PROJECT_ROOT / "data" / "evaluation" / "planner" / "retrieval.json",
    )
    parser.add_argument("--planner-concurrency", type=int, default=16)
    parser.add_argument("--retry-unknown-paid-calls", action="store_true")
    parser.add_argument("--user", default="eval_user_a")
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data" / "evaluation" / "release" / "cuda.json",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.planner_concurrency < 1:
        raise SystemExit("--planner-concurrency must be at least 1")
    args.dataset = args.dataset.resolve()
    args.source_dir = args.source_dir.resolve()
    args.planner_snapshot = args.planner_snapshot.resolve()
    args.output = args.output.resolve()
    os.environ["RAG_DEVICE"] = "cuda"
    os.environ["PARSER_PROVIDER"] = "docling"
    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    from evaluation.workflow_lock import evaluation_index_lock

    with evaluation_index_lock():
        result = asyncio.run(_run(args))
    print(
        json.dumps(
            {
                "selected_profile": result.get("selected_profile"),
                "release_ready": result.get("release_ready"),
                "report": str(args.output),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
