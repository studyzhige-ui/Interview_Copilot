from pathlib import Path
from types import SimpleNamespace

import pytest

import evaluation.career_scenario_eval as scenario_eval
from evaluation.career_scenario_eval import (
    CareerScenarioGateError,
    _pytest_junit_summary,
    _run,
    load_manifest,
    validate_disabled_memory_boundary,
    validate_manifest,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_career_scenario_manifest_covers_every_stage_and_real_tests() -> None:
    result = validate_manifest(load_manifest(), project_root=PROJECT_ROOT)

    assert result["stages"] == [0, 1, 2, 3, 4, 5]
    assert result["scenario_count"] >= 10
    assert len(result["backend_tests"]) >= 20
    assert len(result["frontend_tests"]) >= 12
    assert len(result["stage_specs"]) == 6


def test_memory_gate_keeps_legacy_writer_absent_and_recall_empty() -> None:
    result = validate_disabled_memory_boundary(project_root=PROJECT_ROOT)

    assert result == {
        "automatic_memory_producer": "disabled",
        "memory_recall": "empty",
        "legacy_runtime_paths": "absent",
        "stage_spec": "docs/architecture/stages/stage-5-evaluation-memory.md",
    }


def test_manifest_rejects_missing_stage_without_running_any_product_code(
    tmp_path: Path,
) -> None:
    manifest = load_manifest()
    manifest["scenarios"] = [
        value for value in manifest["scenarios"] if value["stage"] != 5
    ]

    with pytest.raises(CareerScenarioGateError, match="does not cover stages"):
        validate_manifest(manifest, project_root=PROJECT_ROOT)


def test_pytest_junit_summary_reports_exact_mandatory_skips(tmp_path: Path) -> None:
    report = tmp_path / "pytest.xml"
    report.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest" tests="2" skipped="1">
    <testcase classname="tests.test_gate" name="test_ready" />
    <testcase classname="tests.test_gate" name="test_requires_postgres">
      <skipped type="pytest.skip" message="TEST_DATABASE_URL is required" />
    </testcase>
  </testsuite>
</testsuites>
""",
        encoding="utf-8",
    )

    assert _pytest_junit_summary(report) == {
        "valid": True,
        "error": None,
        "tests": 2,
        "skipped": 1,
        "skipped_tests": ["tests.test_gate::test_requires_postgres"],
        "skipped_details": [
            {
                "test": "tests.test_gate::test_requires_postgres",
                "reason": "TEST_DATABASE_URL is required",
            }
        ],
    }


def test_structured_pytest_skip_makes_command_gate_fail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = tmp_path / "pytest.xml"

    def fake_run(*_args, **_kwargs):
        report.write_text(
            """<testsuites><testsuite tests="1" skipped="1">
<testcase classname="tests.test_gate" name="test_external">
<skipped message="external prerequisite missing" />
</testcase></testsuite></testsuites>""",
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(scenario_eval.subprocess, "run", fake_run)

    result = _run(
        ["python", "-m", "pytest", "mandatory-test.py"],
        cwd=tmp_path,
        pytest_junit_path=report,
    )

    assert result["returncode"] == 0
    assert result["passed"] is False
    assert result["pytest_junit"]["skipped"] == 1
    assert result["pytest_junit"]["skipped_details"] == [
        {
            "test": "tests.test_gate::test_external",
            "reason": "external prerequisite missing",
        }
    ]
    assert result["gate_failure"].startswith("mandatory_pytest_scenarios_skipped")
