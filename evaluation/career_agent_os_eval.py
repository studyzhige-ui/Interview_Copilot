"""Release gate for Career Agent OS vertical-slice scenario manifests."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import hashlib
import tempfile
import xml.etree.ElementTree as ET
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


def _contained_file(root: Path, relative: str) -> Path:
    path = Path(relative)
    if not relative or path.is_absolute() or ".." in path.parts:
        raise CareerAgentOSGateError(f"unsafe evidence path: {relative!r}")
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root.resolve()) or not resolved.is_file():
        raise CareerAgentOSGateError(
            f"evidence file is missing or escapes root: {relative!r}"
        )
    return resolved


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
        _contained_file(project_root, relative)

    scenarios = manifest.get("scenarios")
    if not isinstance(scenarios, list):
        raise CareerAgentOSGateError("scenarios must be a list")
    if len(scenarios) != len(VS01_SCENARIOS) or not all(
        isinstance(item, dict) for item in scenarios
    ):
        raise CareerAgentOSGateError(
            "VS-01 requires exactly 15 unique scenario objects"
        )
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
        if coverage == "covered" and not (
            scenario.get("backend_tests") or scenario.get("frontend_tests")
        ):
            raise CareerAgentOSGateError(
                f"{scenario_id}: covered requires executable evidence"
            )
        for relative in scenario.get("backend_tests") or []:
            relative = str(relative)
            _contained_file(project_root, relative)
            if not relative.startswith("backend/tests/") or not relative.endswith(
                ".py"
            ):
                raise CareerAgentOSGateError(
                    f"{scenario_id}: not a backend test: {relative}"
                )
            backend_tests.append(relative)
        for relative in scenario.get("frontend_tests") or []:
            relative = str(relative)
            _contained_file(project_root / "frontend", relative)
            if not relative.startswith("src/") or ".test." not in relative:
                raise CareerAgentOSGateError(
                    f"{scenario_id}: not a frontend test: {relative}"
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


def _executed_evidence(path: Path, bindings: list[str], *, frontend: bool) -> dict:
    """Fresh JUnit only: exit code zero or a skipped suite is not evidence."""
    if not path.is_file():
        return {"passed": False, "error": "test_report_missing"}
    raw = path.read_bytes()
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return {"passed": False, "error": "test_report_invalid"}
    cases = list(root.iter("testcase"))
    covered = set()
    failed = skipped = 0
    for case in cases:
        failed += int(
            case.find("failure") is not None or case.find("error") is not None
        )
        skipped += int(case.find("skipped") is not None)
        name = case.get("classname", "").replace("\\", "/")
        file = case.get("file", "").replace("\\", "/")
        for binding in bindings:
            if frontend:
                match = name.endswith(binding) or file.endswith(binding)
            else:
                # Pytest can report either repository-root modules
                # (backend.tests.*) or backend-root modules (tests.*), depending
                # on its import root. Match only these exact module boundaries;
                # unrelated suffixes must not satisfy a required file binding.
                dotted = binding.removesuffix(".py").replace("/", ".")
                module_names = (dotted, dotted.removeprefix("backend."))
                match = (
                    any(
                        name == module or name.startswith(module + ".")
                        for module in module_names
                    )
                    or file == binding
                    or file.endswith("/" + binding)
                )
            if match:
                covered.add(binding)
    missing = sorted(set(bindings) - covered)
    return {
        "passed": bool(cases) and not failed and not skipped and not missing,
        "tests": len(cases),
        "failures_or_errors": failed,
        "skipped": skipped,
        "missing_bindings": missing,
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def run_gate(
    manifest: dict[str, Any],
    *,
    static_only: bool = False,
    backend_only: bool = False,
    frontend_only: bool = False,
    project_root: Path = PROJECT_ROOT,
) -> dict[str, Any]:
    if sum((static_only, backend_only, frontend_only)) > 1:
        raise CareerAgentOSGateError("gate modes are mutually exclusive")
    validation = validate_manifest(manifest, project_root=project_root)
    commands: list[dict[str, Any]] = []
    reports = {}
    # A newly allocated directory prevents a previous successful report from
    # being reused when today's runner fails before writing its own results.
    with tempfile.TemporaryDirectory(prefix="career-os-gate-") as temporary:
        output = Path(temporary)
        if not static_only and not frontend_only:
            path = output / "backend.xml"
            commands.append(
                _run(
                    [
                        sys.executable,
                        "-m",
                        "pytest",
                        *validation["backend_tests"],
                        "-q",
                        f"--junitxml={path}",
                    ],
                    cwd=project_root,
                )
            )
            reports["backend"] = _executed_evidence(
                path, validation["backend_tests"], frontend=False
            )
        if not static_only and not backend_only:
            path = output / "frontend.xml"
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
                        "--reporter=junit",
                        f"--outputFile={path}",
                    ],
                    cwd=project_root / "frontend",
                )
            )
            reports["frontend"] = _executed_evidence(
                path, validation["frontend_tests"], frontend=True
            )
    full = not (static_only or backend_only or frontend_only)
    executed = (
        bool(commands)
        and all(c["passed"] for c in commands)
        and all(r["passed"] for r in reports.values())
    )
    return {
        "manifest": validation,
        "commands": commands,
        "executed_evidence": reports,
        "validation_passed": True,
        "selected_checks_passed": executed,
        "mode": "static"
        if static_only
        else "backend"
        if backend_only
        else "frontend"
        if frontend_only
        else "full",
        "passed": full
        and validation["release_ready"]
        and executed
        and set(reports) == {"backend", "frontend"},
        "scope": "VS-01 deterministic contracts; not live model or product-quality acceptance",
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
