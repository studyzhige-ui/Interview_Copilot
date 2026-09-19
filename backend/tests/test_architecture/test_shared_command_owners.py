"""Guard actual HTTP/Agent call sites, not a declared ownership inventory.

These static wiring checks complement behavioral authorization/CAS/recovery
suites. They do not prove that two inputs or all runtime paths are equivalent.
"""

import ast
from pathlib import Path

APP_ROOT = Path(__file__).parents[2] / "app"


def _imported_calls(source: str) -> set[str]:
    tree = ast.parse(source)
    imports = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and not node.level:
            imports.update(
                {
                    alias.asname or alias.name: f"{node.module}.{alias.name}"
                    for alias in node.names
                }
            )
        elif isinstance(node, ast.Import):
            imports.update(
                {
                    alias.asname or alias.name.split(".")[0]: alias.name
                    if alias.asname
                    else alias.name.split(".")[0]
                    for alias in node.names
                }
            )

    def target(node):
        if isinstance(node, ast.Name):
            return imports.get(node.id, node.id)
        if isinstance(node, ast.Attribute):
            return f"{target(node.value)}.{node.attr}"
        return ""

    return {
        target(node.func)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and target(node.func).startswith("app.")
    }


def test_http_and_agent_invoke_the_same_current_business_command_owners():
    assert (APP_ROOT / "main.py").is_file()
    calls = {}
    for layer in ("api", "agent_runtime/tools"):
        paths = list((APP_ROOT / layer).rglob("*.py"))
        assert paths, f"ownership scan is empty: {layer}"
        calls[layer] = set().union(
            *(_imported_calls(path.read_text(encoding="utf-8")) for path in paths)
        )
    expected = {
        "app.career.application.profile.upsert_personal_fact",
        "app.career.application.profile.remove_personal_fact",
        "app.career.application.profile.resolve_profile_candidate_items",
        "app.career.application.profile.upsert_profile_direction",
        "app.career.application.profile.set_profile_direction_lifecycle",
        "app.career.application.process.create_job_opportunity",
        "app.career.application.process.append_confirmed_process_event",
        "app.career.application.process.create_next_action",
        "app.career.application.process.edit_next_action",
        "app.career.application.process.plan_next_action",
        "app.career.application.process.complete_next_action",
        "app.career.application.process.close_next_action",
        "app.career.application.artifacts.save_artifact_explicitly",
        "app.career.application.artifacts.record_user_confirmed_submission",
        "app.career.application.resumes.resume_artifact_service.create_resume_artifact",
        "app.career.application.job_descriptions.create_job_description_snapshot",
        "app.career.application.personalization.replace_copilot_preference",
        "app.interviews.application.analysis_intake.create_record_and_dispatch",
        "app.interviews.application.mock_flow.start_mock",
        "app.rag.application.service.rag_service.retrieve",
    }
    for layer, actual in calls.items():
        assert expected <= actual, (layer, sorted(expected - actual))


def test_wiring_scan_requires_a_call_and_resolves_aliases():
    unused = "from app.career.application.profile import upsert_personal_fact"
    assert _imported_calls(unused) == set()
    source = """
from app.career.application import profile as owner
from app.career.application.process import create_next_action as action
import app.interviews.application.mock_flow as mock
owner.upsert_personal_fact(db)
action(db)
mock.start_mock(db)
"""
    assert _imported_calls(source) == {
        "app.career.application.profile.upsert_personal_fact",
        "app.career.application.process.create_next_action",
        "app.interviews.application.mock_flow.start_mock",
    }
