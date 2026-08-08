"""JSON + Markdown report writer.

Consumes the metric dicts returned by ``runners.run_*`` and writes them
to ``data/evaluation/reports/eval_<timestamp>/``. The CLI calls this
when ``--report`` is passed; the pytest layer doesn't (it just asserts
thresholds and discards the numbers).
"""

from __future__ import annotations

import json
import os
import platform
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Make ``app.core.config`` importable without installing the backend package.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_BACKEND_ROOT = _PROJECT_ROOT / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))


# Latency sub-tables we know about. Adding a new latency stat to a
# runner = add a row here. Anything not listed renders as a top-level
# scalar in the metric table.
_LATENCY_KEYS = {
    "latency_ms": "Latency (ms)",
    "planner_latency_ms": "Planner Latency (ms)",
    "retrieval_latency_ms": "Retrieval Latency (ms)",
    "model_ttft_ms": "Model TTFT — Time to First Non-empty Token (ms)",
    "retrieval_to_first_token_ms": "Current Retrieval + Live Model TTFT (ms)",
    "reconstructed_end_to_end_ttft_ms": (
        "Frozen Planner + Current Retrieval + Live Model TTFT (ms)"
    ),
    "generation_e2e_latency_ms": "Generation End-to-End Latency (ms)",
    "post_planner_e2e_latency_ms": "Post-planner Retrieval + Generation Latency (ms)",
    "reconstructed_e2e_latency_ms": (
        "Frozen Planner + Current Retrieval + Live Generation Latency (ms)"
    ),
    "tpot_ms": "TPOT — Time per Output Token, Excluding First (ms)",
    "stream_chunk_gap_ms": "Observed Stream Chunk Gap (ms; not token ITL)",
    "output_tokens": "Output Tokens per Request",
    "output_throughput_tokens_per_second": "Output Throughput (tokens/s)",
}


def hardware_metadata() -> dict[str, Any]:
    """Capture the runtime details required to reproduce a release benchmark."""
    import torch

    cuda_available = torch.cuda.is_available()
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "processor": platform.processor()
        or os.environ.get("PROCESSOR_IDENTIFIER", "unknown"),
        "torch": torch.__version__,
        "cuda_runtime": torch.version.cuda,
        "cuda_available": cuda_available,
        "gpu": torch.cuda.get_device_name(0) if cuda_available else None,
    }


def _timestamped_dir(base: Path) -> Path:
    ts = datetime.now(UTC).strftime("%Y-%m-%d_%H%M%S_%f")
    out = base / f"eval_{ts}_{uuid.uuid4().hex[:8]}"
    out.mkdir(parents=True, exist_ok=False)
    return out


def save_json(data: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _render_metric_table(layer: str, metrics: dict[str, Any]) -> list[str]:
    """Emit one Markdown table for a layer's scalar metrics."""
    lines: list[str] = [
        f"## {layer}",
        "",
        "| Metric | Value |",
        "|--------|-------|",
    ]
    for key, value in metrics.items():
        if (
            key in {"per_sample_details", "ragas_per_sample_metrics"}
            or key in _LATENCY_KEYS
            or isinstance(value, list)
        ):
            continue
        if isinstance(value, dict):
            continue
        if isinstance(value, float):
            lines.append(f"| {key} | {value:.4f} |")
        else:
            lines.append(f"| {key} | {value} |")
    lines.append("")

    for key, values in metrics.items():
        if key in _LATENCY_KEYS or not isinstance(values, dict):
            continue
        lines.extend(
            [
                f"### {key}",
                "",
                "| Key | Value |",
                "|-----|-------|",
            ]
        )
        for item_key, item_value in values.items():
            if isinstance(item_value, float):
                rendered = f"{item_value:.4f}"
            elif isinstance(item_value, (dict, list)):
                rendered = f"`{json.dumps(item_value, ensure_ascii=False)}`"
            else:
                rendered = item_value
            lines.append(f"| {item_key} | {rendered} |")
        lines.append("")

    for key, label in _LATENCY_KEYS.items():
        stats = metrics.get(key)
        if not isinstance(stats, dict):
            continue
        lines.extend(
            [
                f"### {label}",
                "",
                "| Stat | Value |",
                "|------|-------|",
            ]
        )
        for stat_key, stat_value in stats.items():
            if isinstance(stat_value, float):
                lines.append(f"| {stat_key} | {stat_value:.1f} |")
            else:
                lines.append(f"| {stat_key} | {stat_value} |")
        lines.append("")
    return lines


def generate_report(
    *,
    retrieval: dict[str, Any] | None = None,
    generation: dict[str, Any] | None = None,
    trajectory: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    output_dir: Path | None = None,
) -> Path:
    """Write JSON + Markdown reports; return the run directory."""
    from app.core.config import settings

    base = output_dir or (Path(settings.APP_DATA_DIR) / "evaluation" / "reports")
    run_dir = _timestamped_dir(base)

    # ── JSON ──
    full: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "run": metadata or {},
    }
    layer_payloads = [
        ("retrieval", "Layer 1: Retrieval Quality", retrieval),
        ("generation", "Layer 2: Generation Quality (RAGAS)", generation),
        ("trajectory", "Layer 3: Planner Routing", trajectory),
    ]
    for key, _label, payload in layer_payloads:
        if payload is not None:
            full[key] = payload
            save_json(payload, run_dir / f"{key}_details.json")
    save_json(full, run_dir / "report.json")

    # ── Markdown ──
    md: list[str] = [
        "# RAG Evaluation Report",
        "",
        f"**Generated**: {full['generated_at']}",
        "",
    ]
    if metadata:
        md.extend(
            [
                "## Run metadata",
                "",
                "```json",
                json.dumps(metadata, ensure_ascii=False, indent=2),
                "```",
                "",
            ]
        )
    for _key, label, payload in layer_payloads:
        if payload is not None:
            md.extend(_render_metric_table(label, payload))

    md.extend(
        [
            "---",
            f"*Report saved to `{run_dir}`*",
        ]
    )
    (run_dir / "report.md").write_text("\n".join(md), encoding="utf-8")
    return run_dir
