"""Source-derived schema drift gate, separate from semantic/runtime validation."""

import importlib.util
import json
from pathlib import Path
import sys

import pytest
from pydantic import ValidationError

from app.schemas.interview_invitation import ConfirmInterviewInvitation

ROOT = Path(__file__).parents[3]
SCRIPT = ROOT / "scripts/export_shared_contracts.py"


def exporter():
    assert SCRIPT.is_file()
    spec = importlib.util.spec_from_file_location("shared_contract_export", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def resolve(schemas, name):
    value = schemas[name]
    while "$ref" in value:
        value = schemas[value["$ref"].removeprefix("#/components/schemas/")]
    return value


def test_snapshot_is_generated_from_current_pydantic_models_and_refs_are_local():
    module = exporter()
    actual = module.SNAPSHOT.read_text(encoding="utf-8")
    assert actual == module.render_snapshot()
    document = json.loads(actual)
    assert document["openapi"] == "3.1.0"
    schemas = document["components"]["schemas"]
    assert len(schemas) >= 20, "empty schema scans cannot satisfy the contract gate"

    def check(node):
        if isinstance(node, dict):
            if "$ref" in node:
                assert node["$ref"].startswith("#/components/schemas/")
                assert node["$ref"].split("/")[-1] in schemas
            for child in node.values():
                check(child)
        elif isinstance(node, list):
            for child in node:
                check(child)

    check(document)
    request = resolve(schemas, "ConfirmInterviewInvitationRequestContract")
    assert "schema_version" not in request["required"]
    assert request["properties"]["schema_version"]["const"] == 1
    response = resolve(schemas, "ConfirmInterviewInvitationResultResponseContract")
    assert "replayed" in response["required"]
    interaction = resolve(schemas, "AgentInteractionViewResponseContract")
    assert "request" in interaction["required"]
    assert "request_json" not in interaction["properties"]
    candidate = resolve(schemas, "InterviewInvitationCandidateFactsResponseContract")
    assert {"type": "null"} in candidate["properties"]["company_name"]["anyOf"]


def test_check_fails_for_missing_or_stale_snapshot(monkeypatch, tmp_path):
    module = exporter()
    target = tmp_path / "wire.json"
    monkeypatch.setattr(module, "SNAPSHOT", target)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--check"])
    assert module.main() == 1
    target.write_text("{}\n")
    assert module.main() == 1
    target.write_text(module.render_snapshot(), encoding="utf-8")
    assert module.main() == 0


def test_unknown_wire_version_remains_a_runtime_rejection():
    # Snapshot/type generation cannot replace the server's semantic validation.
    with pytest.raises(ValidationError) as error:
        ConfirmInterviewInvitation.model_validate({"schema_version": 2})
    assert any(
        item["loc"] == ("schema_version",) and item["type"] == "literal_error"
        for item in error.value.errors()
    )


def test_codegen_is_pinned_and_ci_checks_both_sides():
    config = json.loads((ROOT / "scripts/contract_codegen/package.json").read_text())
    lock = json.loads((ROOT / "scripts/contract_codegen/package-lock.json").read_text())
    assert config["devDependencies"] == lock["packages"][""]["devDependencies"]
    assert config["devDependencies"]["openapi-typescript"] == "7.13.0"
    assert "--check" in config["scripts"]["check"]
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "scripts/export_shared_contracts.py --check" in workflow
    assert "npm run --prefix ../scripts/contract_codegen check" in workflow
    compatibility = ROOT / "frontend/src/types/shared-protocol-compatibility.ts"
    assert compatibility.is_file()
    assert "RejectUnknownAction" in compatibility.read_text()
