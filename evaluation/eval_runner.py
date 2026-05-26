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
import json
import logging
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

from evaluation.runners import (  # noqa: E402
    filter_by_layer,
    load_dataset,
    prepare_runtime,
    run_generation,
    run_retrieval,
    run_trajectory,
)

LAYERS = ("retrieval", "generation", "trajectory")
_RUNNERS = {
    "retrieval": run_retrieval,
    "generation": run_generation,
    "trajectory": run_trajectory,
}


def _print_layer_summary(layer: str, result: dict[str, Any]) -> None:
    """Pretty-print one layer's summary (skip the per-sample detail list)."""
    printable = {k: v for k, v in result.items() if k != "per_sample_details"}
    print(json.dumps(printable, ensure_ascii=False, indent=2))


async def _run_layers(
    layers: list[str],
    rows: list[dict[str, Any]],
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
        result = await _RUNNERS[layer](layer_rows)
        results[layer] = result
        elapsed = time.perf_counter() - start
        print(f"\n  Completed in {elapsed:.1f}s")
        _print_layer_summary(layer, result)
        print()
    return results


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Interview Copilot RAG Evaluation Suite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Run all evaluation layers",
    )
    parser.add_argument(
        "--layer", choices=LAYERS,
        help="Run a specific layer",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Take the first N rows of the dataset",
    )
    parser.add_argument(
        "--sample", type=int, default=None,
        help="Randomly sample N rows (after layer filtering). Mutually "
             "exclusive with --limit.",
    )
    parser.add_argument(
        "--seed", type=int, default=0,
        help="Random seed for --sample (default 0, reproducible).",
    )
    parser.add_argument(
        "--report", action="store_true",
        help="Write JSON + Markdown report under data/evaluation/reports/",
    )
    parser.add_argument(
        "--verbose", "-v", action="count", default=0,
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

    logging.basicConfig(
        level=logging.DEBUG if args.verbose >= 2
              else logging.INFO if args.verbose >= 1
              else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    prepare_runtime()
    rows = load_dataset(limit=args.limit)
    if args.sample:
        random.seed(args.seed)
        rows = random.sample(rows, min(args.sample, len(rows)))
    print(f"Loaded {len(rows)} dataset rows.\n")

    layers = list(LAYERS) if args.all else [args.layer]
    results = asyncio.run(_run_layers(layers, rows))

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
