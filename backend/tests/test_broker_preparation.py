"""Preparation follows exactly the active mainline model roles."""

import sys
from types import SimpleNamespace

import pytest
from scripts import prepare_local_inference as prepare

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="broker deployment requires Linux/WSL2"
)


@pytest.mark.parametrize(
    "mode,provider,enabled",
    [
        ("auto", "local_whisperx", True),
        ("auto", "openai", False),
        ("pyannote", "openai", True),
        ("none", "local_whisperx", False),
    ],
)
def test_preparation_uses_configured_model_and_current_execution_policy(
    tmp_path, monkeypatch, mode, provider, enabled
):
    monkeypatch.setattr(prepare.settings, "DIARIZATION_MODE", mode)
    monkeypatch.setattr(prepare.settings, "TRANSCRIPTION_PROVIDER", provider)
    monkeypatch.setattr(
        prepare.settings, "DIARIZATION_MODEL_ID", "configured/community-model"
    )

    def inspect(model, **kwargs):
        return SimpleNamespace(
            loadable_candidate=True,
            path=str(tmp_path / "weights"),
            layout="pipeline_bundle"
            if model == "configured/community-model"
            else "transformers",
        )

    monkeypatch.setattr(prepare, "inspect_model", inspect)
    config = prepare.build_config(
        python=sys.executable,
        device="cpu",
        runtime_dir=tmp_path / "run",
        model_root=tmp_path,
        cache_root=tmp_path,
    )
    roles = {spec.role: spec for spec in config.models}
    assert ("diarization" in roles) == enabled
    if enabled:
        assert roles["diarization"].model_id == "configured/community-model"
        assert roles["diarization"].python == sys.executable
