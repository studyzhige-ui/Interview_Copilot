import os

import pytest


def test_runtime_selection_persists_to_custom_file(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_SELECTION_FILE", str(tmp_path / "model_selection.json"))

    import app.core.model_registry as model_registry

    selection = model_registry.update_runtime_selection({"fast": "deepseek-v4-flash"})
    assert selection["fast"] == "deepseek-v4-flash"
    assert model_registry.get_runtime_selection()["fast"] == "deepseek-v4-flash"


def test_agent_role_requires_function_calling(monkeypatch):
    monkeypatch.setenv("MODEL_SELECTION_FILE", os.devnull)

    import app.core.model_registry as model_registry

    with pytest.raises(ValueError):
        model_registry.validate_role_update("agent", "deepseek-reasoner")


def test_legacy_deepseek_selection_falls_back_to_v4_defaults(monkeypatch):
    monkeypatch.setenv("MODEL_SELECTION_FILE", os.devnull)

    import app.core.model_registry as model_registry

    selection = model_registry._normalize_selection(  # noqa: SLF001
        {
            "primary": "deepseek-reasoner",
            "fast": "deepseek-chat",
            "agent": "deepseek-chat",
        }
    )
    assert selection == {
        "primary": "deepseek-v4-flash",
        "fast": "deepseek-v4-flash",
        "agent": "deepseek-v4-pro",
    }
