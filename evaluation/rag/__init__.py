"""New RAG evaluation subsystem (Phase D / docs/zh/rag-evaluation-optimization-plan.md).

Layered offline runners (planner / retrieval / citation / generation / ingestion)
over versioned gold datasets — replacing the old top-level ``evaluation/`` harness
(frozen). The CODE here is version-controlled; gold datasets
(``evaluation/rag/datasets/*.jsonl``) embed fixture content and stay local (see
.gitignore); run reports land under ``data/evaluation/rag/reports/``.

Importing this package puts the backend ``app`` package on ``sys.path`` so runners
can call the live planner / retriever / generation the same way the app does
(mirrors the old harness's bootstrap). CLI entry point: ``python -m evaluation.rag.cli``.
"""
from __future__ import annotations

import sys
from pathlib import Path

# evaluation/rag/__init__.py -> parents[2] is the repo root; backend/ holds ``app``.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_ROOT = _REPO_ROOT / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

# Versioned gold datasets (gitignored content, tracked dir layout).
DATASETS_DIR = Path(__file__).resolve().parent / "datasets"
# Run-output reports — under data/ so they're already gitignored.
REPORTS_DIR = _REPO_ROOT / "data" / "evaluation" / "rag" / "reports"

__all__ = ["DATASETS_DIR", "REPORTS_DIR"]
