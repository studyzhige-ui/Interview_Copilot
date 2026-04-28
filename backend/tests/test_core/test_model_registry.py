import os

import pytest


def test_runtime_selection_persists_to_custom_file(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_SELECTION_FILE", str(tmp_path / "model_selection.json"))

    import app.core.model_registry as model_registry

    selection = model_registry.update_runtime_selection({"fast": "deepseek-chat"})
    assert selection["fast"] == "deepseek-chat"
    assert model_registry.get_runtime_selection()["fast"] == "deepseek-chat"


def test_agent_role_requires_function_calling(monkeypatch):
    monkeypatch.setenv("MODEL_SELECTION_FILE", os.devnull)

    import app.core.model_registry as model_registry

    with pytest.raises(ValueError):
        model_registry.validate_role_update("agent", "deepseek-reasoner")
