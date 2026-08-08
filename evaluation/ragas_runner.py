"""Fixed-sample RAGAS judging with bounded concurrency and durable progress."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import inspect
import json
import logging
import os
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FORMAL_SAMPLE_PATH = Path(__file__).with_name("ragas_formal_sample.json")
CHECKPOINT_ROOT = PROJECT_ROOT / "data" / "evaluation" / "ragas" / "checkpoints"
SNAPSHOT_ROOT = PROJECT_ROOT / "data" / "evaluation" / "ragas" / "snapshots"
ANSWER_CACHE_ROOT = PROJECT_ROOT / "data" / "evaluation" / "ragas" / "answers"
METRIC_TIMEOUT_SECONDS = 360
GENERATION_SNAPSHOT_VERSION = 1
ANSWER_CACHE_VERSION = 2
METRIC_KEYS = (
    "faithfulness",
    "answer_relevancy",
    "context_precision_with_reference",
    "context_recall",
    "answer_correctness",
)


@contextmanager
def generation_workflow_lock():
    """Serialize the complete live check/formal workflow across processes."""
    from filelock import FileLock, Timeout

    CHECKPOINT_ROOT.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(CHECKPOINT_ROOT / "generation-workflow.lock"))
    try:
        with lock.acquire(timeout=0):
            yield
    except Timeout as exc:
        raise RuntimeError(
            "Another RAGAS compatibility or formal workflow is already running"
        ) from exc


def formal_sample_manifest() -> dict[str, Any]:
    return json.loads(FORMAL_SAMPLE_PATH.read_text(encoding="utf-8"))


def select_formal_rows(
    rows: list[dict[str, Any]],
    *,
    compatibility_check: bool = False,
) -> list[dict[str, Any]]:
    """Select the pinned 50-row answerable set, or its first compatibility row."""
    sample_ids = [str(value) for value in formal_sample_manifest()["sample_ids"]]
    by_id = {str(row.get("id")): row for row in rows}
    missing = [sample_id for sample_id in sample_ids if sample_id not in by_id]
    if missing:
        raise ValueError(f"RAGAS formal sample ids missing from dataset: {missing}")
    selected = [by_id[sample_id] for sample_id in sample_ids]
    if len(selected) != 50 or any(
        row.get("expected_retrieval") is not True for row in selected
    ):
        raise ValueError("RAGAS formal sample must contain 50 answerable rows")
    return selected[:1] if compatibility_check else selected


def _metric_factories(ragas_llm, ragas_embeddings):
    from ragas.metrics.collections import (
        AnswerCorrectness,
        AnswerRelevancy,
        ContextPrecisionWithReference,
        ContextRecall,
        Faithfulness,
    )

    return (
        ("faithfulness", lambda: Faithfulness(llm=ragas_llm)),
        (
            "answer_relevancy",
            lambda: AnswerRelevancy(llm=ragas_llm, embeddings=ragas_embeddings),
        ),
        (
            "context_precision_with_reference",
            lambda: ContextPrecisionWithReference(llm=ragas_llm),
        ),
        ("context_recall", lambda: ContextRecall(llm=ragas_llm)),
        (
            "answer_correctness",
            lambda: AnswerCorrectness(llm=ragas_llm, embeddings=ragas_embeddings),
        ),
    )


def _metric_kwargs(metric, item: dict[str, Any]) -> dict[str, Any]:
    from ragas.metrics.collections import (
        AnswerCorrectness,
        AnswerRelevancy,
        ContextPrecisionWithReference,
        ContextRecall,
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
    if isinstance(metric, AnswerRelevancy):
        return {
            "user_input": item["user_input"],
            "response": item["response"],
        }
    if isinstance(metric, AnswerCorrectness):
        return {
            "user_input": item["user_input"],
            "response": item["response"],
            "reference": item["reference"],
        }
    raise TypeError(f"Unsupported RAGAS metric: {type(metric).__name__}")


def _evaluation_contract_fingerprint(
    *, generator_config: Any, judge_config: Any
) -> str:
    from app.core.config import settings
    from evaluation.llm_factory import (
        RAGAS_JUDGE_MAX_RETRIES,
        RAGAS_JUDGE_MAX_TOKENS,
        RAGAS_JUDGE_TEMPERATURE,
        RAGAS_JUDGE_TIMEOUT_SECONDS,
        build_ragas_embeddings,
        build_ragas_judge,
    )

    payload = {
        "version": 2,
        "metrics": METRIC_KEYS,
        "ragas_version": importlib.metadata.version("ragas"),
        "metric_contract_sha256": hashlib.sha256(
            (
                inspect.getsource(_metric_factories)
                + inspect.getsource(_metric_kwargs)
                + inspect.getsource(build_ragas_judge)
                + inspect.getsource(build_ragas_embeddings)
            ).encode("utf-8")
        ).hexdigest(),
        "generator": {
            "api_base": generator_config.api_base,
            "model": generator_config.model,
            "thinking_mode": generator_config.thinking_mode,
        },
        "judge": {
            "api_base": judge_config.api_base,
            "model": judge_config.model,
            "thinking_mode": judge_config.thinking_mode,
            "temperature": RAGAS_JUDGE_TEMPERATURE,
            "max_tokens": RAGAS_JUDGE_MAX_TOKENS,
            "timeout_seconds": RAGAS_JUDGE_TIMEOUT_SECONDS,
            "max_retries": RAGAS_JUDGE_MAX_RETRIES,
        },
        "embeddings": {
            "provider": settings.EMBEDDING_PROVIDER,
            "model": settings.EMBEDDING_MODEL,
        },
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sample_fingerprint(item: dict[str, Any], contract_fingerprint: str) -> str:
    metric_input = {
        key: item[key]
        for key in ("user_input", "response", "retrieved_contexts", "reference")
    }
    encoded = json.dumps(
        {"contract_fingerprint": contract_fingerprint, "metric_input": metric_input},
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _ragas_slice_summary(
    samples: list[dict[str, Any]],
    *,
    key: str,
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for sample in samples:
        grouped.setdefault(str(sample.get(key) or "unknown"), []).append(sample)
    result: dict[str, dict[str, Any]] = {}
    for name, rows in sorted(grouped.items()):
        summary: dict[str, Any] = {
            "samples": len(rows),
            "completed_samples": sum(bool(row["completed"]) for row in rows),
        }
        for metric in METRIC_KEYS:
            values = [
                float(row["metrics"][metric])
                for row in rows
                if row["metrics"].get(metric) is not None
            ]
            summary[metric] = round(sum(values) / len(values), 4) if values else None
        result[name] = summary
    return result


def _generation_contract_sha256() -> str:
    import app.conversation.query_planner as planner_module
    import app.prompts.chat as chat_prompts_module
    import app.rag.evidence as evidence_module
    import app.rag.knowledge_retriever as knowledge_retriever_module
    import app.rag.retriever as retriever_module
    from evaluation.runners import _run_generation, run_generation

    source = "".join(
        inspect.getsource(value)
        for value in (
            run_generation,
            _run_generation,
            planner_module,
            chat_prompts_module,
            evidence_module,
            knowledge_retriever_module,
            retriever_module,
        )
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _compatibility_identity() -> dict[str, Any]:
    from app.core.config import settings
    from evaluation.llm_factory import (
        load_generator_llm_config,
        load_judge_llm_config,
    )
    from evaluation.index_provenance import validate_evaluation_index
    from evaluation.rag_release import _current_runtime_contract

    generator = load_generator_llm_config()
    judge = load_judge_llm_config()
    return {
        "version": 1,
        "formal_sample_manifest": formal_sample_manifest(),
        "compatibility_sample_id": formal_sample_manifest()["sample_ids"][0],
        "generation_contract_sha256": _generation_contract_sha256(),
        "evaluation_contract": _evaluation_contract_fingerprint(
            generator_config=generator,
            judge_config=judge,
        ),
        "credential_fingerprints": {
            "generator": hashlib.sha256(generator.api_key.encode("utf-8")).hexdigest(),
            "judge": hashlib.sha256(judge.api_key.encode("utf-8")).hexdigest(),
        },
        "evaluation_index_fingerprint": validate_evaluation_index()["fingerprint"],
        "rag_runtime_contract": _current_runtime_contract(),
        "rag": {
            "chunk_tokens": settings.RAG_CHUNK_TOKENS,
            "chunk_overlap": settings.RAG_CHUNK_OVERLAP,
            "candidate_count": settings.RAG_CANDIDATE_COUNT,
            "final_count": settings.RAG_FINAL_COUNT,
            "min_score": settings.RAG_MIN_SCORE,
            "score_margin": settings.RAG_SCORE_MARGIN,
            "embedding_model": settings.EMBEDDING_MODEL,
            "reranker_model": settings.RERANKER_MODEL,
        },
    }


def _compatibility_marker_path() -> tuple[Path, dict[str, Any]]:
    identity = _compatibility_identity()
    fingerprint = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return CHECKPOINT_ROOT / "compatibility" / f"{fingerprint}.json", identity


def _load_compatibility_marker() -> dict[str, Any]:
    path, identity = _compatibility_marker_path()
    if not path.is_file():
        raise RuntimeError(
            "No successful matching RAGAS compatibility check was found; run "
            "--ragas-profile check before --ragas-profile formal"
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("identity") != identity:
        raise RuntimeError("RAGAS compatibility marker does not match this run")
    verified_at = datetime.fromisoformat(str(payload.get("verified_at")))
    if datetime.now(UTC) - verified_at > timedelta(hours=24):
        raise RuntimeError("RAGAS compatibility check is older than 24 hours")
    if (
        not payload.get("generator_live_probe")
        or int(payload.get("judge_live_requests") or 0) < 1
    ):
        raise RuntimeError("RAGAS compatibility marker has no live provider proof")
    return payload


def require_compatibility_check() -> None:
    """Fail before a formal run unless the matching one-row check passed."""
    _load_compatibility_marker()


def require_compatibility_answer_cache(path: Path) -> None:
    payload = _load_compatibility_marker()
    if payload.get("answer_cache_fingerprint") != path.stem:
        raise RuntimeError(
            "Formal RAGAS cannot reuse the compatibility-check answer cache"
        )


def compatibility_metric_proof(item: dict[str, Any]) -> dict[str, Any]:
    from evaluation.llm_factory import (
        load_generator_llm_config,
        load_judge_llm_config,
    )

    contract = _evaluation_contract_fingerprint(
        generator_config=load_generator_llm_config(),
        judge_config=load_judge_llm_config(),
    )
    fingerprint = _sample_fingerprint(item, contract)
    path = CHECKPOINT_ROOT / contract / f"{fingerprint}.jsonl"
    sample_id = str(item.get("id") or "")
    records = _load_checkpoint(path, fingerprint)
    successful = sorted(
        metric
        for metric in METRIC_KEYS
        if records.get((sample_id, metric), {}).get("status") == "success"
    )
    if successful != sorted(METRIC_KEYS):
        raise RuntimeError(
            "Compatibility-check metric checkpoints are incomplete; run check again"
        )
    return {
        "sample_fingerprint": fingerprint,
        "successful_metrics": successful,
    }


def require_compatibility_metric_cache(item: dict[str, Any]) -> None:
    payload = _load_compatibility_marker()
    if payload.get("metric_cache_proof") != compatibility_metric_proof(item):
        raise RuntimeError(
            "Formal RAGAS cannot reuse all compatibility-check metric checkpoints"
        )


def invalidate_compatibility_check() -> None:
    """Invalidate prior proof before starting a new live compatibility probe."""
    path, _identity = _compatibility_marker_path()
    path.unlink(missing_ok=True)


def _record_compatibility_check(
    *,
    generator_live_probe: bool,
    judge_live_requests: int,
    answer_cache_fingerprint: str,
    metric_cache_proof: dict[str, Any],
) -> Path:
    path, identity = _compatibility_marker_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    _write_json_fsync(
        temporary,
        {
            "identity": identity,
            "verified_at": datetime.now(UTC).isoformat(),
            "generator_live_probe": generator_live_probe,
            "judge_live_requests": judge_live_requests,
            "answer_cache_fingerprint": answer_cache_fingerprint,
            "metric_cache_proof": metric_cache_proof,
        },
    )
    os.replace(temporary, path)
    return path


def _generation_answer_identity(item: dict[str, Any]) -> dict[str, Any]:
    from evaluation.llm_factory import (
        EVALUATION_GENERATOR_MAX_RETRIES,
        EVALUATION_GENERATOR_MAX_TOKENS,
        EVALUATION_GENERATOR_TEMPERATURE,
        EVALUATION_GENERATOR_TIMEOUT_SECONDS,
        load_generator_llm_config,
    )

    generator = load_generator_llm_config()
    return {
        "version": ANSWER_CACHE_VERSION,
        "generator": {
            "api_base": generator.api_base,
            "model": generator.model,
            "thinking_mode": generator.thinking_mode,
            "temperature": EVALUATION_GENERATOR_TEMPERATURE,
            "max_tokens": EVALUATION_GENERATOR_MAX_TOKENS,
            "timeout_seconds": EVALUATION_GENERATOR_TIMEOUT_SECONDS,
            "max_retries": EVALUATION_GENERATOR_MAX_RETRIES,
        },
        "request": item["request"],
    }


def load_generation_answer(
    item: dict[str, Any],
) -> tuple[dict[str, Any] | None, Path]:
    """Load a paid answer only when its full generation input still matches."""
    identity = _generation_answer_identity(item)
    fingerprint = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    path = ANSWER_CACHE_ROOT / f"{fingerprint}.json"
    if not path.is_file():
        return None, path
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("identity") != identity:
        raise ValueError(f"RAGAS answer cache mismatch: {path}")
    measurement = payload.get("measurement")
    if not isinstance(measurement, dict):
        raise ValueError(f"RAGAS answer cache is invalid: {path}")
    return measurement, path


def save_generation_answer(
    path: Path,
    item: dict[str, Any],
    measurement: dict[str, Any],
) -> None:
    """Persist one generated answer atomically before later samples run."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    _write_json_fsync(
        temporary,
        {
            "identity": _generation_answer_identity(item),
            "measurement": measurement,
        },
    )
    os.replace(temporary, path)


def _write_json_fsync(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())


async def load_or_create_generation_answer(
    item: dict[str, Any],
    generate: Callable[[], Awaitable[dict[str, Any]]],
    *,
    retry_unknown_paid_calls: bool = False,
    force_refresh: bool = False,
) -> tuple[dict[str, Any], Path, bool]:
    """Create one paid answer under a per-identity cross-process lock."""
    from filelock import FileLock, Timeout

    cached, path = load_generation_answer(item)
    if cached is not None and not force_refresh:
        return cached, path, True
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(path.with_suffix(".lock")))
    in_flight = path.with_suffix(".inflight.json")
    try:
        with lock.acquire(timeout=0):
            cached, path = load_generation_answer(item)
            if cached is not None and not force_refresh:
                in_flight.unlink(missing_ok=True)
                return cached, path, True
            if in_flight.is_file() and not retry_unknown_paid_calls:
                raise RuntimeError(
                    "A prior answer request has unknown payment state; pass "
                    "--retry-unknown-paid-calls only after checking provider usage"
                )
            in_flight.unlink(missing_ok=True)
            _write_json_fsync(
                in_flight,
                {"identity": _generation_answer_identity(item)},
            )
            measurement = await generate()
            save_generation_answer(path, item, measurement)
            in_flight.unlink(missing_ok=True)
            return measurement, path, False
    except Timeout as exc:
        raise RuntimeError(
            f"The same evaluation answer is already being generated: {item['id']}"
        ) from exc


def persist_generation_snapshot(
    scored_data: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], Path]:
    """Persist the exact answers and contexts before any judge request starts."""
    from app.core.config import settings
    from evaluation.llm_factory import load_generator_llm_config

    generator = load_generator_llm_config()
    stable_samples = scored_data
    identity = {
        "version": GENERATION_SNAPSHOT_VERSION,
        "generator": {
            "api_base": generator.api_base,
            "model": generator.model,
            "thinking_mode": generator.thinking_mode,
        },
        "generation_contract_sha256": _generation_contract_sha256(),
        "rag": {
            "candidate_count": settings.RAG_CANDIDATE_COUNT,
            "final_count": settings.RAG_FINAL_COUNT,
            "min_score": settings.RAG_MIN_SCORE,
            "score_margin": settings.RAG_SCORE_MARGIN,
            "embedding_model": settings.EMBEDDING_MODEL,
            "reranker_model": settings.RERANKER_MODEL,
        },
        "samples": stable_samples,
    }
    fingerprint = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    path = SNAPSHOT_ROOT / f"{fingerprint}.json"
    from filelock import FileLock, Timeout

    path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(path.with_suffix(".lock")))
    try:
        with lock.acquire(timeout=0):
            if path.is_file():
                payload = json.loads(path.read_text(encoding="utf-8"))
                stored_identity = payload.get("identity")
                stored_fingerprint = hashlib.sha256(
                    json.dumps(
                        stored_identity,
                        ensure_ascii=False,
                        sort_keys=True,
                    ).encode("utf-8")
                ).hexdigest()
                if (
                    payload.get("fingerprint") != fingerprint
                    or stored_fingerprint != fingerprint
                    or stored_identity != identity
                    or payload.get("samples") != stable_samples
                ):
                    raise ValueError(f"RAGAS generation snapshot mismatch: {path}")
                return stable_samples, path

            temporary = path.with_suffix(".tmp")
            _write_json_fsync(
                temporary,
                {
                    "fingerprint": fingerprint,
                    "identity": identity,
                    "samples": stable_samples,
                },
            )
            os.replace(temporary, path)
            return stable_samples, path
    except Timeout as exc:
        raise RuntimeError(
            "The same generation snapshot is being persisted by another process"
        ) from exc


def _load_checkpoint(
    path: Path,
    fingerprint: str,
    *,
    repair_truncated_tail: bool = False,
) -> dict[tuple[str, str], dict]:
    records: dict[tuple[str, str], dict] = {}
    if not path.is_file():
        return records
    raw_lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    for index, line in enumerate(raw_lines):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            is_truncated_tail = index == len(raw_lines) - 1 and not line.endswith("\n")
            if not is_truncated_tail:
                raise ValueError(f"RAGAS checkpoint is corrupt: {path}") from exc
            if not repair_truncated_tail:
                raise RuntimeError(
                    "RAGAS checkpoint has a truncated final record with unknown "
                    "payment state; pass --retry-unknown-paid-calls only after "
                    "checking provider usage"
                ) from exc
            temporary = path.with_suffix(path.suffix + ".repair")
            with temporary.open("w", encoding="utf-8") as handle:
                handle.writelines(raw_lines[:index])
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            break
        if record.get("fingerprint") != fingerprint:
            raise ValueError(f"RAGAS checkpoint fingerprint mismatch: {path}")
        records[(str(record["sample_id"]), str(record["metric"]))] = record
    return records


def _append_checkpoint(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


async def _score_with_ragas(
    scored_data: list[dict[str, Any]],
    *,
    retry_errors: bool = False,
    retry_unknown_paid_calls: bool = False,
    force_live: bool = False,
) -> dict[str, Any]:
    """Judge all supplied samples and resume completed sample/metric pairs."""
    if not scored_data:
        return {
            **dict.fromkeys(METRIC_KEYS),
            "ragas_judged_samples": 0,
            "ragas_answerable_samples": 0,
            "ragas_metric_valid_samples": {},
        }

    from evaluation.llm_factory import (
        build_ragas_embeddings,
        build_ragas_judge,
        load_generator_llm_config,
        load_judge_llm_config,
    )

    generator = load_generator_llm_config()
    judge_config = load_judge_llm_config()
    if generator.model.strip().lower() == judge_config.model.strip().lower():
        raise ValueError("RAGAS judge must be independent from the answer generator")
    contract_fingerprint = _evaluation_contract_fingerprint(
        generator_config=generator,
        judge_config=judge_config,
    )
    checkpoint_directory = CHECKPOINT_ROOT / contract_fingerprint
    usage_checkpoint_path = CHECKPOINT_ROOT / f"{contract_fingerprint}.usage.jsonl"
    sample_fingerprints = [
        _sample_fingerprint(item, contract_fingerprint) for item in scored_data
    ]
    checkpoint_paths = [
        checkpoint_directory / f"{fingerprint}.jsonl"
        for fingerprint in sample_fingerprints
    ]
    completed: dict[tuple[str, str], dict] = {}
    for item, fingerprint, checkpoint_path in zip(
        scored_data,
        sample_fingerprints,
        checkpoint_paths,
    ):
        sample_id = str(item.get("id") or "")
        for (_stored_id, metric), record in _load_checkpoint(
            checkpoint_path,
            fingerprint,
            repair_truncated_tail=retry_unknown_paid_calls,
        ).items():
            completed[(sample_id, metric)] = record
    in_flight_paths = {
        (str(item.get("id") or ""), metric): checkpoint_path.with_suffix(
            f".{hashlib.sha256(metric.encode('utf-8')).hexdigest()[:8]}.inflight"
        )
        for item, checkpoint_path in zip(scored_data, checkpoint_paths)
        for metric in METRIC_KEYS
    }
    unknown = [path for path in in_flight_paths.values() if path.is_file()]
    if unknown and not retry_unknown_paid_calls:
        raise RuntimeError(
            "RAGAS has requests with unknown payment state; pass "
            "--retry-unknown-paid-calls only after checking provider usage"
        )
    if retry_unknown_paid_calls:
        for path in unknown:
            path.unlink(missing_ok=True)
    concurrency = max(1, int(os.getenv("EVAL_JUDGE_CONCURRENCY", "4")))
    semaphore = asyncio.Semaphore(concurrency)
    write_lock = asyncio.Lock()
    ragas_judge = build_ragas_judge(
        usage_checkpoint_path=usage_checkpoint_path,
        retry_unknown_paid_calls=retry_unknown_paid_calls,
    )
    usage_before_run = ragas_judge.usage.snapshot()
    ragas_embeddings = build_ragas_embeddings()
    factories = _metric_factories(ragas_judge.llm, ragas_embeddings)

    async def score_sample(index: int, item: dict[str, Any]) -> None:
        sample_id = str(item.get("id") or f"sample-{index}")
        sample_fingerprint = sample_fingerprints[index - 1]
        checkpoint_path = checkpoint_paths[index - 1]
        async with semaphore:
            for metric_key, metric_factory in factories:
                previous = completed.get((sample_id, metric_key))
                if (
                    not force_live
                    and previous is not None
                    and (previous.get("status") == "success" or not retry_errors)
                ):
                    continue
                started = time.perf_counter()
                record: dict[str, Any] = {
                    "fingerprint": sample_fingerprint,
                    "contract_fingerprint": contract_fingerprint,
                    "sample_id": sample_id,
                    "metric": metric_key,
                }
                in_flight = in_flight_paths[(sample_id, metric_key)]
                _write_json_fsync(
                    in_flight,
                    {
                        "contract_fingerprint": contract_fingerprint,
                        "sample_id": sample_id,
                        "metric": metric_key,
                    },
                )
                failure: Exception | None = None
                try:
                    metric = metric_factory()
                    async with asyncio.timeout(METRIC_TIMEOUT_SECONDS):
                        result = await metric.ascore(**_metric_kwargs(metric, item))
                    value = result.value if hasattr(result, "value") else float(result)
                    if value is None or value != value:
                        raise ValueError("metric returned no finite value")
                    record.update(status="success", value=float(value))
                except Exception as exc:  # noqa: BLE001 - persisted metric failure
                    failure = exc
                    record.update(
                        status="error",
                        payment_state="unknown",
                        error_type=type(exc).__name__,
                        error=str(exc)[:500],
                    )
                    logger.warning(
                        "[RAGAS %s] sample=%s error=%s: %s",
                        metric_key,
                        sample_id,
                        type(exc).__name__,
                        exc,
                    )
                record["elapsed_seconds"] = round(time.perf_counter() - started, 4)
                async with write_lock:
                    _append_checkpoint(checkpoint_path, record)
                    completed[(sample_id, metric_key)] = record
                    if failure is None:
                        in_flight.unlink(missing_ok=True)
                if failure is not None:
                    raise RuntimeError(
                        f"RAGAS {metric_key} failed with unknown payment state"
                    ) from failure
        logger.info(
            "[RAGAS %d/%d] sample=%s complete", index, len(scored_data), sample_id
        )

    tasks = [
        asyncio.create_task(score_sample(index, item))
        for index, item in enumerate(scored_data, 1)
    ]
    try:
        await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    finally:
        await ragas_judge.aclose()

    values = {
        key: [
            float(record["value"])
            for (sample_id, metric), record in completed.items()
            if metric == key and record.get("status") == "success"
        ]
        for key in METRIC_KEYS
    }
    completed_samples = sum(
        all(
            completed.get((str(item.get("id")), metric), {}).get("status") == "success"
            for metric in METRIC_KEYS
        )
        for item in scored_data
    )
    errors = sum(record.get("status") == "error" for record in completed.values())
    per_sample_metrics = []
    for item in scored_data:
        sample_id = str(item.get("id") or "")
        metric_values = {
            metric: (
                float(record["value"])
                if (record := completed.get((sample_id, metric), {})).get("status")
                == "success"
                else None
            )
            for metric in METRIC_KEYS
        }
        per_sample_metrics.append(
            {
                "id": sample_id,
                "language": item.get("language", "unknown"),
                "difficulty": item.get("difficulty", "unknown"),
                "source_format": item.get("source_format", "unknown"),
                "domain": item.get("domain", "unknown"),
                "completed": all(value is not None for value in metric_values.values()),
                "metrics": metric_values,
            }
        )
    scores = {
        key: round(sum(metric_values) / len(metric_values), 4)
        if metric_values
        else None
        for key, metric_values in values.items()
    }
    scores.update(
        {
            "ragas_judged_samples": len(scored_data),
            "ragas_completed_samples": completed_samples,
            "ragas_answerable_samples": len(scored_data),
            "ragas_metric_valid_samples": {
                key: len(metric_values) for key, metric_values in values.items()
            },
            "ragas_error_count": errors,
            "ragas_per_sample_metrics": per_sample_metrics,
            "ragas_by_language": _ragas_slice_summary(
                per_sample_metrics, key="language"
            ),
            "ragas_by_difficulty": _ragas_slice_summary(
                per_sample_metrics, key="difficulty"
            ),
            "ragas_by_source_format": _ragas_slice_summary(
                per_sample_metrics, key="source_format"
            ),
            "ragas_checkpoint_directory": str(checkpoint_directory),
            "ragas_evaluation_contract": contract_fingerprint,
            "judge_usage_checkpoint_path": str(usage_checkpoint_path),
            "judge_concurrency": concurrency,
            "generator_model": generator.model,
            "judge_model": judge_config.model,
            "judge_relationship": (
                "same_model_as_generator"
                if judge_config.model.strip().lower() == generator.model.strip().lower()
                else "independent_model"
            ),
            "judge_usage_this_run": ragas_judge.usage.summary(
                judge_config.model,
                since=usage_before_run,
            ),
            "judge_usage_contract_lifetime": ragas_judge.usage.summary(
                judge_config.model
            ),
            "ragas_metric_directions": {key: "higher_is_better" for key in METRIC_KEYS},
        }
    )
    return scores


async def score_with_ragas(
    scored_data: list[dict[str, Any]],
    *,
    retry_errors: bool = False,
    retry_unknown_paid_calls: bool = False,
    force_live: bool = False,
) -> dict[str, Any]:
    """Run one fingerprint per process; persisted successes are resumable."""
    from filelock import FileLock, Timeout

    from evaluation.llm_factory import (
        load_generator_llm_config,
        load_judge_llm_config,
    )

    lock_key = _evaluation_contract_fingerprint(
        generator_config=load_generator_llm_config(),
        judge_config=load_judge_llm_config(),
    )
    CHECKPOINT_ROOT.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(CHECKPOINT_ROOT / f"{lock_key}.lock"))
    try:
        with lock.acquire(timeout=0):
            scores = await _score_with_ragas(
                scored_data,
                retry_errors=retry_errors,
                retry_unknown_paid_calls=retry_unknown_paid_calls,
                force_live=force_live,
            )
            return scores
    except Timeout as exc:
        raise RuntimeError(
            "The same RAGAS sample is already running in another process"
        ) from exc


__all__ = [
    "ANSWER_CACHE_ROOT",
    "FORMAL_SAMPLE_PATH",
    "METRIC_KEYS",
    "compatibility_metric_proof",
    "formal_sample_manifest",
    "generation_workflow_lock",
    "invalidate_compatibility_check",
    "load_or_create_generation_answer",
    "load_generation_answer",
    "persist_generation_snapshot",
    "require_compatibility_answer_cache",
    "require_compatibility_check",
    "require_compatibility_metric_cache",
    "score_with_ragas",
    "save_generation_answer",
    "select_formal_rows",
]
