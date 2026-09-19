from __future__ import annotations

import pytest

from evaluation.career_agent_os_eval import (
    CareerAgentOSGateError,
    VS01_SCENARIOS,
    load_manifest,
    validate_manifest,
)


def test_vs01_manifest_targets_new_blueprint_and_registers_all_scenarios() -> None:
    result = validate_manifest(load_manifest())

    assert result["scenario_count"] == 15
    assert set(result["scenario_ids"]) == VS01_SCENARIOS
    assert result["incomplete_scenarios"] == ["VS01-S09", "VS01-S14"]
    assert result["release_ready"] is False
    assert (
        "backend/tests/test_career/test_interview_invitation_operations.py"
        in result["backend_tests"]
    )
    assert "src/pages/today/TodayPage.test.tsx" in result["frontend_tests"]


def test_vs01_manifest_cannot_point_back_to_superseded_blueprint() -> None:
    manifest = load_manifest()
    manifest["architecture"] = "docs/architecture/full-cycle-career-copilot.md"

    with pytest.raises(CareerAgentOSGateError, match="approved Career Agent OS"):
        validate_manifest(manifest)


def test_duplicate_scenario_cannot_count_as_coverage():
    manifest = load_manifest()
    manifest["scenarios"].append(dict(manifest["scenarios"][0]))
    with pytest.raises(CareerAgentOSGateError, match="unique"):
        validate_manifest(manifest)


@pytest.mark.parametrize("value", ["../README.md", "/etc/passwd", "--help"])
def test_evidence_paths_cannot_escape_or_be_cli_options(value):
    manifest = load_manifest()
    manifest["scenarios"][0]["backend_tests"] = [value]
    with pytest.raises(CareerAgentOSGateError):
        validate_manifest(manifest)


def test_covered_without_any_execution_binding_is_invalid():
    manifest = load_manifest()
    manifest["scenarios"][0].update(backend_tests=[], frontend_tests=[])
    with pytest.raises(CareerAgentOSGateError, match="executable"):
        validate_manifest(manifest)


def test_static_validation_cannot_be_release_acceptance():
    from evaluation.career_agent_os_eval import run_gate

    manifest = load_manifest()
    for scenario in manifest["scenarios"]:
        scenario["coverage"] = "covered"
    result = run_gate(manifest, static_only=True)
    assert result["validation_passed"] is True
    assert result["passed"] is False
    assert result["selected_checks_passed"] is False


@pytest.mark.parametrize(
    "content",
    [
        None,
        "bad xml",
        "<testsuite/>",
        '<testsuite><testcase classname="tests.other" name="a"/></testsuite>',
        '<testsuite><testcase classname="tests.test_one" name="a"><skipped/></testcase></testsuite>',
    ],
)
def test_empty_skipped_missing_or_unrelated_junit_cannot_pass(tmp_path, content):
    from evaluation.career_agent_os_eval import _executed_evidence

    path = tmp_path / "fresh.xml"
    if content is not None:
        path.write_text(content)
    assert not _executed_evidence(path, ["backend/tests/test_one.py"], frontend=False)[
        "passed"
    ]


def test_actual_bound_junit_is_required_and_hashed(tmp_path):
    from evaluation.career_agent_os_eval import _executed_evidence

    path = tmp_path / "fresh.xml"
    path.write_text(
        '<testsuite><testcase classname="tests.test_one" name="a"/></testsuite>'
    )
    result = _executed_evidence(path, ["backend/tests/test_one.py"], frontend=False)
    assert result["passed"] and result["tests"] == 1 and len(result["sha256"]) == 64
