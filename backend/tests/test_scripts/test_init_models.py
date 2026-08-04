from __future__ import annotations

from scripts import init_models


def test_write_env_updates_only_selected_keys(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# 保留中文注释\nEMBEDDING_PROVIDER=siliconflow\nUNCHANGED=value\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(init_models, "ENV_FILE", env_file)
    for key in ("EMBEDDING_PROVIDER", "EMBEDDING_MODEL"):
        monkeypatch.setenv(key, "test-original")

    init_models._write_env(
        {
            "EMBEDDING_PROVIDER": "local",
            "EMBEDDING_MODEL": "BAAI/bge-m3",
        }
    )

    text = env_file.read_text(encoding="utf-8")
    assert "# 保留中文注释" in text
    assert "EMBEDDING_PROVIDER=local" in text
    assert "EMBEDDING_MODEL=BAAI/bge-m3" in text
    assert "UNCHANGED=value" in text


def test_recommended_selection_persists_complete_local_profile(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("APP_EDITION=community\n", encoding="utf-8")
    monkeypatch.setattr(init_models, "ENV_FILE", env_file)
    monkeypatch.setattr(init_models, "_choice", lambda *_args, **_kwargs: 1)
    for key in init_models.RECOMMENDED_LOCAL_CONFIG:
        monkeypatch.setenv(key, "test-original")

    selected = init_models._interactive_selection()

    assert selected == {
        "embedding",
        "reranker",
        "whisper",
        "diarization",
        "docling",
    }
    text = env_file.read_text(encoding="utf-8")
    for key, value in init_models.RECOMMENDED_LOCAL_CONFIG.items():
        assert f"{key}={value}" in text


def test_custom_selection_can_build_a_hybrid_profile(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "EMBEDDING_PROVIDER=siliconflow\nTRANSCRIPTION_PROVIDER=siliconflow\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(init_models, "ENV_FILE", env_file)
    for key in (
        "EMBEDDING_PROVIDER",
        "EMBEDDING_MODEL",
        "EMBEDDING_DIM",
        "PARSER_PROVIDER",
    ):
        monkeypatch.setenv(key, "test-original")
    monkeypatch.setattr(init_models, "_choice", lambda *_args, **_kwargs: 2)
    monkeypatch.setattr(
        init_models,
        "_yes_no",
        lambda prompt, **_kwargs: (
            prompt.startswith("Use a local embedding")
            or prompt.startswith("Use Docling")
        ),
    )
    monkeypatch.setattr(
        init_models,
        "_select_model",
        lambda role: ("org/custom-embedding", "768"),
    )

    selected = init_models._interactive_selection()

    assert selected == {"embedding", "docling"}
    text = env_file.read_text(encoding="utf-8")
    assert "EMBEDDING_PROVIDER=local" in text
    assert "EMBEDDING_MODEL=org/custom-embedding" in text
    assert "EMBEDDING_DIM=768" in text
    assert "PARSER_PROVIDER=docling" in text
    assert "TRANSCRIPTION_PROVIDER=siliconflow" in text


def test_cancel_does_not_modify_environment(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    original = "APP_EDITION=community\n"
    env_file.write_text(original, encoding="utf-8")
    monkeypatch.setattr(init_models, "ENV_FILE", env_file)
    monkeypatch.setattr(init_models, "_choice", lambda *_args, **_kwargs: 4)

    assert init_models._interactive_selection() == set()
    assert env_file.read_text(encoding="utf-8") == original


def test_diarization_without_local_whisper_uses_hybrid_mode(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("TRANSCRIPTION_PROVIDER=openai\n", encoding="utf-8")
    monkeypatch.setattr(init_models, "ENV_FILE", env_file)
    monkeypatch.setattr(init_models, "_choice", lambda *_args, **_kwargs: 2)
    monkeypatch.setattr(
        init_models,
        "_yes_no",
        lambda prompt, **_kwargs: prompt.startswith("Use local speaker"),
    )
    monkeypatch.setattr(
        init_models,
        "_select_model",
        lambda role: (
            "pyannote-community/speaker-diarization-community-1",
            None,
        ),
    )
    for key in ("DIARIZATION_MODE", "DIARIZATION_MODEL_ID"):
        monkeypatch.setenv(key, "test-original")

    assert init_models._interactive_selection() == {"diarization"}
    text = env_file.read_text(encoding="utf-8")
    assert "TRANSCRIPTION_PROVIDER=openai" in text
    assert "DIARIZATION_MODE=pyannote" in text
