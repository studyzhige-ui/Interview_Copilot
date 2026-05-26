"""JSON + Markdown report writer.

Consumes the metric dicts returned by ``runners.run_*`` and writes them
to ``data/evaluation/reports/eval_<timestamp>/``. The CLI calls this
when ``--report`` is passed; the pytest layer doesn't (it just asserts
thresholds and discards the numbers).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# Make ``app.core.config`` importable for the EVAL_DIR setting.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_BACKEND_ROOT = _PROJECT_ROOT / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))


# Latency sub-tables we know about. Adding a new latency stat to a
# runner = add a row here. Anything not listed renders as a top-level
# scalar in the metric table.
_LATENCY_KEYS = {
    "latency_ms":            "Latency (ms)",
    "retrieval_latency_ms":  "Retrieval Latency (ms)",
    "ttfb_ms":               "TTFB — Time to First Token (ms)",
    "e2e_latency_ms":        "End-to-End QA Latency (ms)",
}


def _timestamped_dir(base: Path) -> Path:
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out = base / f"eval_{ts}"
    out.mkdir(parents=True, exist_ok=True)
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
        if key == "per_sample_details" or key in _LATENCY_KEYS:
            continue
        if isinstance(value, dict):
            continue  # nested dict (only expected for unknown latency keys)
        if isinstance(value, float):
            lines.append(f"| {key} | {value:.4f} |")
        else:
            lines.append(f"| {key} | {value} |")
    lines.append("")

    for key, label in _LATENCY_KEYS.items():
        stats = metrics.get(key)
        if not isinstance(stats, dict):
            continue
        lines.extend([
            f"### {label}",
            "",
            "| Stat | Value |",
            "|------|-------|",
        ])
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
    output_dir: Path | None = None,
) -> Path:
    """Write JSON + Markdown reports; return the run directory."""
    from app.core.config import settings

    base = output_dir or (Path(settings.EVAL_DIR) / "reports")
    run_dir = _timestamped_dir(base)

    # ── JSON ──
    full: dict[str, Any] = {"generated_at": datetime.now().isoformat()}
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
    for _key, label, payload in layer_payloads:
        if payload is not None:
            md.extend(_render_metric_table(label, payload))

    md.extend([
        "---",
        f"*Report saved to `{run_dir}`*",
    ])
    (run_dir / "report.md").write_text("\n".join(md), encoding="utf-8")
    return run_dir
