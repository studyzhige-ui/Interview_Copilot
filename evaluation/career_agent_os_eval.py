"""Release gate for Career Agent OS vertical-slice scenario manifests."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = Path(__file__).with_name("career_agent_os_scenarios.json")
VS01_SCENARIOS = frozenset(f"VS01-S{index:02d}" for index in range(1, 16))


class CareerAgentOSGateError(RuntimeError):
    """The target-architecture scenario manifest is structurally invalid."""


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CareerAgentOSGateError("scenario manifest must be an object")
    return value


def validate_manifest(
    manifest: dict[str, Any],
    *,
    project_root: Path = PROJECT_ROOT,
) -> dict[str, Any]:
    expected_architecture = "docs/architecture/career-agent-os-blueprint.md"
    if manifest.get("architecture") != expected_architecture:
        raise CareerAgentOSGateError(
            "manifest must target the approved Career Agent OS Blueprint"
        )
    required_documents = [
        expected_architecture,
        str(manifest.get("vertical_slice") or ""),
        *[str(item) for item in manifest.get("contracts") or []],
    ]
    for relative in required_documents:
        if not relative or not (project_root / relative).is_file():
            raise CareerAgentOSGateError(f"required document is missing: {relative!r}")

    scenarios = manifest.get("scenarios")
    if not isinstance(scenarios, list):
        raise CareerAgentOSGateError("scenarios must be a list")
    actual_ids = {
        str(item.get("id") or "") for item in scenarios if isinstance(item, dict)
    }
    if actual_ids != VS01_SCENARIOS:
        raise CareerAgentOSGateError(
            f"VS-01 scenario set mismatch: missing={sorted(VS01_SCENARIOS - actual_ids)}, "
            f"extra={sorted(actual_ids - VS01_SCENARIOS)}"
        )

    incomplete: list[str] = []
    backend_tests: list[str] = []
    frontend_tests: list[str] = []
    for scenario in scenarios:
        scenario_id = str(scenario["id"])
        coverage = scenario.get("coverage")
        if coverage not in {"covered", "partial", "planned"}:
            raise CareerAgentOSGateError(
                f"{scenario_id}: invalid coverage {coverage!r}"
            )
        if coverage != "covered":
            incomplete.append(scenario_id)
        if not str(scenario.get("claim") or "").strip():
            raise CareerAgentOSGateError(f"{scenario_id}: claim is required")
        for relative in scenario.get("backend_tests") or []:
            relative = str(relative)
            if not (project_root / relative).is_file():
                raise CareerAgentOSGateError(
                    f"{scenario_id}: missing backend test {relative}"
                )
            backend_tests.append(relative)
        for relative in scenario.get("frontend_tests") or []:
            relative = str(relative)
            if not (project_root / "frontend" / relative).is_file():
                raise CareerAgentOSGateError(
                    f"{scenario_id}: missing frontend test {relative}"
                )
            frontend_tests.append(relative)
    return {
        "scenario_count": len(scenarios),
        "scenario_ids": sorted(actual_ids),
        "incomplete_scenarios": sorted(incomplete),
        "release_ready": not incomplete,
        "backend_tests": list(dict.fromkeys(backend_tests)),
        "frontend_tests": list(dict.fromkeys(frontend_tests)),
    }


def _run(command: list[str], *, cwd: Path) -> dict[str, Any]:
    started = time.perf_counter()
    environment = os.environ.copy()
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
        returncode = 124
        timed_out = True
    return {
        "command": command,
        "returncode": returncode,
        "timed_out": timed_out,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "passed": returncode == 0,
    }


def run_gate(
    manifest: dict[str, Any],
    *,
    static_only: bool = False,
    backend_only: bool = False,
    frontend_only: bool = False,
    project_root: Path = PROJECT_ROOT,
) -> dict[str, Any]:
    validation = validate_manifest(manifest, project_root=project_root)
    commands: list[dict[str, Any]] = []
    if not static_only and not frontend_only:
        commands.append(
            _run(
                [sys.executable, "-m", "pytest", *validation["backend_tests"], "-q"],
                cwd=project_root,
            )
        )
    if not static_only and not backend_only:
        commands.append(
            _run(
                [
                    "npm.cmd" if os.name == "nt" else "npm",
                    "run",
                    "test:run",
                    "--",
                    *validation["frontend_tests"],
                    "--maxWorkers=1",
                    "--no-file-parallelism",
                ],
                cwd=project_root / "frontend",
            )
        )
    return {
        "manifest": validation,
        "commands": commands,
        "passed": validation["release_ready"]
        and all(item["passed"] for item in commands),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--static-only", action="store_true")
    parser.add_argument("--backend-only", action="store_true")
    parser.add_argument("--frontend-only", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.backend_only and args.frontend_only:
        raise SystemExit("--backend-only and --frontend-only are mutually exclusive")
    result = run_gate(
        load_manifest(args.manifest),
        static_only=args.static_only,
        backend_only=args.backend_only,
        frontend_only=args.frontend_only,
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + "\n", encoding="utf-8")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
