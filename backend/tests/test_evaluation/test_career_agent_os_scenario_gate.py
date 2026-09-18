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
