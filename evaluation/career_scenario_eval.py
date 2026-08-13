"""Executable Stage 0-5 career-product regression matrix.

The existing RAG evaluator measures retrieval and generation quality.  This
runner covers the product and runtime contracts in the authoritative career
architecture by executing their real backend and frontend tests.  It does not
replace those tests or create a second implementation of the domain logic.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = Path(__file__).with_name("career_scenarios.json")
REQUIRED_STAGES = frozenset(range(6))
STAGE_SPECS = tuple(
    f"docs/architecture/stages/stage-{stage}-{slug}.md"
    for stage, slug in (
        (0, "runtime"),
        (1, "attachments"),
        (2, "career-state"),
        (3, "artifacts-interviews"),
        (4, "connectors-automation"),
        (5, "evaluation-memory"),
    )
)


class CareerScenarioGateError(RuntimeError):
    """The scenario manifest or a release invariant is incomplete."""


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CareerScenarioGateError("career scenario manifest must be an object")
    return value


def validate_manifest(
    manifest: dict[str, Any],
    *,
    project_root: Path = PROJECT_ROOT,
) -> dict[str, Any]:
    scenarios = manifest.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise CareerScenarioGateError("career scenario manifest has no scenarios")

    seen_ids: set[str] = set()
    stages: set[int] = set()
    backend_tests: set[str] = set()
    frontend_tests: set[str] = set()
    for scenario in scenarios:
        if not isinstance(scenario, dict):
            raise CareerScenarioGateError("every scenario must be an object")
        scenario_id = str(scenario.get("id") or "").strip()
        if not scenario_id or scenario_id in seen_ids:
            raise CareerScenarioGateError(
                f"invalid or duplicate scenario id: {scenario_id!r}"
            )
        seen_ids.add(scenario_id)
        stage = scenario.get("stage")
        if not isinstance(stage, int) or stage not in REQUIRED_STAGES:
            raise CareerScenarioGateError(f"{scenario_id}: invalid stage {stage!r}")
        stages.add(stage)
        claims = scenario.get("claims")
        if not isinstance(claims, list) or not all(
            str(item).strip() for item in claims
        ):
            raise CareerScenarioGateError(f"{scenario_id}: claims must be non-empty")
        for value in scenario.get("backend_tests") or []:
            backend_tests.add(str(value))
        for value in scenario.get("frontend_tests") or []:
            frontend_tests.add(str(value))

    missing_stages = REQUIRED_STAGES - stages
    if missing_stages:
        raise CareerScenarioGateError(
            f"manifest does not cover stages: {sorted(missing_stages)}"
        )
    for relative in STAGE_SPECS:
        if not (project_root / relative).is_file():
            raise CareerScenarioGateError(
                f"stage implementation spec is missing: {relative}"
            )
    for relative in sorted(backend_tests):
        path = project_root / relative
        if not path.is_file():
            raise CareerScenarioGateError(
                f"backend scenario test is missing: {relative}"
            )
    for relative in sorted(frontend_tests):
        path = project_root / "frontend" / relative
        if not path.is_file():
            raise CareerScenarioGateError(
                f"frontend scenario test is missing: {relative}"
            )
    return {
        "scenario_count": len(scenarios),
        "stages": sorted(stages),
        "backend_tests": sorted(backend_tests),
        "frontend_tests": sorted(frontend_tests),
        "stage_specs": list(STAGE_SPECS),
    }


def validate_disabled_memory_boundary(
    *,
    project_root: Path = PROJECT_ROOT,
) -> dict[str, Any]:
    forbidden_paths = (
        "backend/app/agent_runtime/tools/memory.py",
        "backend/app/services/memory/realtime_extraction.py",
        "backend/app/services/memory/dreaming_worker.py",
        "backend/app/services/memory/v3_context_loader.py",
    )
    present = [value for value in forbidden_paths if (project_root / value).exists()]
    if present:
        raise CareerScenarioGateError(
            "legacy automatic Memory runtime remains enabled: " + ", ".join(present)
        )

    engine = (project_root / "backend/app/conversation/engine.py").read_text(
        encoding="utf-8"
    )
    if 'memory_block=""' not in engine:
        raise CareerScenarioGateError(
            "Engine must explicitly assemble an empty Memory Recall until the gate passes"
        )
    tools_init = (
        project_root / "backend/app/agent_runtime/tools/__init__.py"
    ).read_text(encoding="utf-8")
    if "tools.memory" in tools_init or "save_memory" in tools_init:
        raise CareerScenarioGateError("legacy Memory Tool remains registered")
    spec = project_root / "docs/architecture/stages/stage-5-evaluation-memory.md"
    if not spec.is_file():
        raise CareerScenarioGateError("Memory Stage Spec is missing")
    return {
        "automatic_memory_producer": "disabled",
        "memory_recall": "empty",
        "legacy_runtime_paths": "absent",
        "stage_spec": spec.relative_to(project_root).as_posix(),
    }


def _pytest_junit_summary(path: Path) -> dict[str, Any]:
    """Read pytest's stable JUnit contract; never scrape console prose."""

    if not path.is_file():
        return {
            "valid": False,
            "error": "pytest_junit_report_missing",
            "tests": 0,
            "skipped": 0,
            "skipped_tests": [],
            "skipped_details": [],
        }
    try:
        root = ET.parse(path).getroot()  # noqa: S314 - local pytest output
    except (ET.ParseError, OSError):
        return {
            "valid": False,
            "error": "pytest_junit_report_invalid",
            "tests": 0,
            "skipped": 0,
            "skipped_tests": [],
            "skipped_details": [],
        }
    cases = root.findall(".//testcase")
    skipped_cases: list[tuple[str, str]] = []
    for case in cases:
        skipped = case.find("skipped")
        if skipped is None:
            continue
        test_id = "::".join(
            value
            for value in (
                str(case.get("classname") or "").strip(),
                str(case.get("name") or "").strip(),
            )
            if value
        )
        reason = str(skipped.get("message") or skipped.text or "").strip()
        skipped_cases.append((test_id, reason))
    return {
        "valid": True,
        "error": None,
        "tests": len(cases),
        "skipped": len(skipped_cases),
        "skipped_tests": [test_id for test_id, _reason in skipped_cases],
        "skipped_details": [
            {"test": test_id, "reason": reason} for test_id, reason in skipped_cases
        ],
    }


def _run(
    command: list[str],
    *,
    cwd: Path,
    pytest_junit_path: Path | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    environment = os.environ.copy()
    # Release validation is correctness work, not model serving.  Keeping it on
    # CPU prevents independent pytest collections from each loading an embedding
    # model onto the same GPU.  Provider/model behaviour is exercised through
    # protocol-faithful fakes in the scenario tests.
    environment["CUDA_VISIBLE_DEVICES"] = "-1"
    environment.setdefault("TOKENIZERS_PARALLELISM", "false")
    try:
        completed = subprocess.run(  # noqa: S603
            command,
            cwd=cwd,
            check=False,
            env=environment,
            timeout=30 * 60,
        )
        returncode = completed.returncode
        timed_out = False
    except subprocess.TimeoutExpired:
        # subprocess.run terminates and waits for the direct child.  Keeping
        # the timeout inside this runner avoids the orphaned pytest processes
        # that an outer shell timeout can otherwise leave behind on Windows.
        returncode = 124
        timed_out = True
    result = {
        "command": command,
        "returncode": returncode,
        "timed_out": timed_out,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    passed = returncode == 0
    if pytest_junit_path is not None:
        junit = _pytest_junit_summary(pytest_junit_path)
        result["pytest_junit"] = junit
        if not junit["valid"]:
            passed = False
            result["gate_failure"] = str(junit["error"])
        elif junit["skipped"]:
            passed = False
            result["gate_failure"] = (
                "mandatory_pytest_scenarios_skipped; satisfy the reported "
                "external prerequisites and rerun"
            )
    result["passed"] = passed
    return result


def _ordered_unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))


def run_matrix(
    manifest: dict[str, Any],
    *,
    run_backend: bool,
    run_frontend: bool,
    project_root: Path = PROJECT_ROOT,
) -> dict[str, Any]:
    validation = validate_manifest(manifest, project_root=project_root)
    result: dict[str, Any] = {
        "manifest": validation,
        "memory_gate": validate_disabled_memory_boundary(project_root=project_root),
        "commands": [],
    }
    commands: list[dict[str, Any]] = result["commands"]
    if run_backend:
        with tempfile.TemporaryDirectory(prefix="career-scenario-pytest-") as temp_dir:
            junit_path = Path(temp_dir) / "mandatory-scenarios.xml"
            command = [
                sys.executable,
                "-m",
                "pytest",
                *_ordered_unique(validation["backend_tests"]),
                "-q",
                "--junitxml",
                str(junit_path),
            ]
            commands.append(
                _run(
                    command,
                    cwd=project_root,
                    pytest_junit_path=junit_path,
                )
            )
    if run_frontend:
        command = [
            "npm.cmd" if os.name == "nt" else "npm",
            "run",
            "test:run",
            "--",
            *_ordered_unique(validation["frontend_tests"]),
            "--maxWorkers=1",
            "--no-file-parallelism",
        ]
        commands.append(_run(command, cwd=project_root / "frontend"))
    result["passed"] = all(bool(item["passed"]) for item in commands)
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--static-only", action="store_true")
    parser.add_argument("--backend-only", action="store_true")
    parser.add_argument("--frontend-only", action="store_true")
    parser.add_argument("--report", type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.backend_only and args.frontend_only:
        raise SystemExit("--backend-only and --frontend-only are mutually exclusive")
    manifest = load_manifest(args.manifest)
    result = run_matrix(
        manifest,
        run_backend=not args.static_only and not args.frontend_only,
        run_frontend=not args.static_only and not args.backend_only,
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + "\n", encoding="utf-8")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
