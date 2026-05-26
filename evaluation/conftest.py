"""Pytest fixtures for the evaluation suite.

The actual evaluation runs are session-scoped — running L1/L2/L3
through the production pipeline is expensive (Milvus + reranker + LLM
calls), so each test file pulls from a precomputed metric dict instead
of re-traversing the dataset per assertion. Yields a 10-20× speed-up
on the full suite.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest

# Make ``backend/app/...`` importable for the production code paths the
# runners call into.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from evaluation.runners import (  # noqa: E402
    filter_by_layer,
    load_dataset,
    prepare_runtime,
    run_generation,
    run_retrieval,
    run_trajectory,
)

EVAL_USER_A = "eval_user_a"
EVAL_USER_B = "eval_user_b"


@pytest.fixture(scope="session", autouse=True)
def _bootstrap_runtime() -> None:
    """Set HF env, init embeddings + LLM Settings, warm the reranker."""
    prepare_runtime()


@pytest.fixture(scope="session")
def golden_dataset() -> list[dict[str, Any]]:
    rows = load_dataset()
    if not rows:
        pytest.skip("Golden dataset is empty.")
    return rows


@pytest.fixture(scope="session")
def retrieval_dataset(golden_dataset: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = filter_by_layer(golden_dataset, "retrieval")
    if not rows:
        pytest.skip("No retrieval-layer rows.")
    return rows


@pytest.fixture(scope="session")
def generation_dataset(golden_dataset: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = filter_by_layer(golden_dataset, "generation")
    if not rows:
        pytest.skip("No generation-layer rows.")
    return rows


@pytest.fixture(scope="session")
def trajectory_dataset(golden_dataset: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = filter_by_layer(golden_dataset, "trajectory")
    if not rows:
        pytest.skip("No trajectory-layer rows.")
    return rows


# ── One-shot runner fixtures ───────────────────────────────────────────
# Each layer's runner is expensive (one Milvus call per row, plus LLM
# calls for L2/L3). Cache the result for the whole session so every
# assertion file in that layer reads the same metric dict.


@pytest.fixture(scope="session")
def retrieval_metrics(retrieval_dataset: list[dict[str, Any]]) -> dict[str, Any]:
    return asyncio.run(run_retrieval(retrieval_dataset))


@pytest.fixture(scope="session")
def generation_metrics(generation_dataset: list[dict[str, Any]]) -> dict[str, Any]:
    return asyncio.run(run_generation(generation_dataset))


@pytest.fixture(scope="session")
def trajectory_metrics(trajectory_dataset: list[dict[str, Any]]) -> dict[str, Any]:
    return asyncio.run(run_trajectory(trajectory_dataset))
