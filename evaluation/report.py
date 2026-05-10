"""Evaluation report generator.

Produces JSON and Markdown reports from evaluation results and saves them
to ``data/evaluation/reports/<run_id>/``.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def _run_dir(base: Path) -> Path:
    """Create a timestamped run directory."""
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    run_dir = base / f"eval_{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def save_json(data: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def generate_report(
    *,
    retrieval: dict[str, Any] | None = None,
    generation: dict[str, Any] | None = None,
    trajectory: dict[str, Any] | None = None,
    output_dir: Path | None = None,
) -> Path:
    """Generate JSON + Markdown report and return the report directory path."""
    import sys
    from pathlib import Path as _P

    project_root = _P(__file__).resolve().parents[1]
    sys.path.insert(0, str(project_root / "backend"))
    from app.core.config import settings

    base = output_dir or (Path(settings.EVAL_DIR) / "reports")
    run_dir = _run_dir(base)

    # --- JSON ---
    full_result: dict[str, Any] = {"generated_at": datetime.now().isoformat()}
    if retrieval:
        full_result["retrieval"] = retrieval
        save_json(retrieval, run_dir / "retrieval_details.json")
    if generation:
        full_result["generation"] = generation
        save_json(generation, run_dir / "generation_details.json")
    if trajectory:
        full_result["trajectory"] = trajectory
        save_json(trajectory, run_dir / "trajectory_details.json")
    save_json(full_result, run_dir / "report.json")

    # --- Markdown ---
    md_lines = [
        "# RAG Evaluation Report",
        "",
        f"**Generated**: {full_result['generated_at']}",
        "",
    ]

    if retrieval:
        md_lines.extend([
            "## Layer 1: Retrieval Quality",
            "",
            "| Metric | Value |",
            "|--------|-------|",
        ])
        for key, value in retrieval.items():
            if isinstance(value, (int, float)):
                md_lines.append(f"| {key} | {value:.4f} |" if isinstance(value, float) else f"| {key} | {value} |")
        md_lines.append("")

    if generation:
        md_lines.extend([
            "## Layer 2: Generation Quality (RAGAS)",
            "",
            "| Metric | Value |",
            "|--------|-------|",
        ])
        for key, value in generation.items():
            if key in ("per_sample_details",):
                continue
            if isinstance(value, dict):
                continue  # handled below as sub-tables
            if isinstance(value, (int, float)):
                md_lines.append(f"| {key} | {value:.4f} |" if isinstance(value, float) else f"| {key} | {value} |")
        md_lines.append("")

        # Latency sub-tables
        for latency_key, label in [
            ("retrieval_latency", "Retrieval Latency (ms)"),
            ("ttfb", "TTFB — Time to First Token (ms)"),
            ("e2e_latency", "End-to-End QA Latency (ms)"),
        ]:
            lat = generation.get(latency_key)
            if isinstance(lat, dict):
                md_lines.extend([
                    f"### {label}",
                    "",
                    "| Stat | Value |",
                    "|------|-------|",
                ])
                for k, v in lat.items():
                    md_lines.append(f"| {k} | {v:.1f} |" if isinstance(v, float) else f"| {k} | {v} |")
                md_lines.append("")

    if trajectory:
        md_lines.extend([
            "## Layer 3: Agent Trajectory",
            "",
            "| Metric | Value |",
            "|--------|-------|",
        ])
        for key, value in trajectory.items():
            if isinstance(value, (int, float)):
                md_lines.append(f"| {key} | {value:.4f} |" if isinstance(value, float) else f"| {key} | {value} |")
        md_lines.append("")

    md_lines.extend([
        "---",
        f"*Report saved to `{run_dir}`*",
    ])

    (run_dir / "report.md").write_text("\n".join(md_lines), encoding="utf-8")
    return run_dir
