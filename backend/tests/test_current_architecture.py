"""Production imports must resolve; model execution has one explicit owner."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "app"


def test_all_application_sources_parse_as_utf8():
    sources = list(ROOT.rglob("*.py"))
    assert len(sources) > 100
    for path in sources:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_whisperx_uses_broker_and_shared_context_has_no_retired_owner():
    tree = ast.parse(
        (ROOT / "media/application/whisperx_engine.py").read_text(encoding="utf-8")
    )
    imports = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert "app.local_inference.diarization" in imports
    assert not any(
        name.startswith(("pyannote", "whisperx.diarize")) for name in imports
    )
    assert not (ROOT / "agent_runtime/tool_result_storage.py").exists()
    assert not (ROOT / "rag/qwen_local.py").exists()


def test_model_probe_and_broker_children_are_not_imported_by_business_modules():
    for path in ROOT.rglob("*.py"):
        if "local_inference" in path.parts or path.name == "model_probe_child.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.module not in {
                    "app.local_inference.child",
                    "app.local_inference.pyannote_audio",
                }, path


def test_memory_has_one_selective_owner_and_no_automatic_producer_default():
    from app.core.config import Settings

    assert Settings.model_fields["AGENT_MEMORY_PRODUCER_ENABLED"].default is False
    assert "from app.memory.recall import recall" in (
        ROOT / "conversation/engine.py"
    ).read_text(encoding="utf-8")
    assert "save_memory" not in (ROOT / "agent_runtime/tools/__init__.py").read_text(
        encoding="utf-8"
    )
    for retired in (
        "agent_runtime/tools/memory.py",
        "services/memory/realtime_extraction.py",
        "services/memory/dreaming_worker.py",
    ):
        assert not (ROOT / retired).exists()
