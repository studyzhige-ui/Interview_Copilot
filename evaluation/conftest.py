"""Pytest fixtures shared across evaluation tests.

These fixtures set up the backend import path, database connections,
Milvus vector store, reranker model, and golden dataset loading.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Python path bootstrap — make backend importable
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.hf_runtime import prepare_hf_runtime  # noqa: E402
from app.core.config import settings  # noqa: E402


# ---------------------------------------------------------------------------
# Golden dataset path
# ---------------------------------------------------------------------------

GOLDEN_DATASET_PATH = Path(__file__).with_name("golden_dataset.jsonl")

EVAL_USER_A = "eval_user_a"
EVAL_USER_B = "eval_user_b"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def _bootstrap_runtime():
    """Prepare HuggingFace runtime and reranker for the entire test session."""
    prepare_hf_runtime()
    from app.rag.retriever import init_reranker

    init_reranker()


@pytest.fixture(scope="session")
def golden_dataset() -> list[dict[str, Any]]:
    """Load the golden evaluation dataset."""
    if not GOLDEN_DATASET_PATH.exists():
        pytest.skip(f"Golden dataset not found: {GOLDEN_DATASET_PATH}")
    rows: list[dict[str, Any]] = []
    with GOLDEN_DATASET_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    if not rows:
        pytest.skip("Golden dataset is empty.")
    return rows


@pytest.fixture(scope="session")
def retrieval_dataset(golden_dataset: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter golden dataset to retrieval-layer test cases."""
    rows = [r for r in golden_dataset if r.get("layer") in ("retrieval", "all")]
    if not rows:
        pytest.skip("No retrieval-layer rows in golden dataset.")
    return rows


@pytest.fixture(scope="session")
def generation_dataset(golden_dataset: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter golden dataset to generation-layer test cases."""
    rows = [r for r in golden_dataset if r.get("layer") in ("generation", "all")]
    if not rows:
        pytest.skip("No generation-layer rows in golden dataset.")
    return rows


@pytest.fixture(scope="session")
def trajectory_dataset(golden_dataset: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter golden dataset to trajectory-layer test cases."""
    rows = [r for r in golden_dataset if r.get("layer") in ("trajectory", "all")]
    if not rows:
        pytest.skip("No trajectory-layer rows in golden dataset.")
    return rows
