from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.core import hf_runtime
from app.core.config import settings
from app.core.model_assets import inspect_directory, inspect_model, local_path
from scripts import init_models
from scripts.doctor_local import build_report


def safetensor(path: Path, data=b"\0\0\0\0") -> None:
    header = json.dumps(
        {"weight": {"dtype": "F32", "shape": [1], "data_offsets": [0, 4]}}
    ).encode()
    path.write_bytes(len(header).to_bytes(8, "little") + header + data)


def transformer(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "config.json").write_text('{"model_type":"bert"}')
    (path / "tokenizer.json").write_text("{}")
    safetensor(path / "model.safetensors")
    return path


def inspect(tmp_path, revision=None):
    return inspect_model(
        "org/model",
        model_root=tmp_path / "models",
        cache_root=tmp_path / "hub",
        revision=revision,
    )


def manifest(path, *, revision="a" * 40):
    files = {}
    for name in ("config.json", "tokenizer.json", "model.safetensors"):
        raw = (path / name).read_bytes()
        files[name] = {"size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    (path / ".copilot-snapshot.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "model_id": "org/model",
                "revision": revision,
                "files": files,
            }
        )
    )


def test_no_directory_creation_and_readme_not_weights(tmp_path):
    assert inspect(tmp_path).status == "missing"
    assert not list(tmp_path.iterdir())
    root = tmp_path / "models/org--model"
    root.mkdir(parents=True)
    (root / "README.md").write_text("a model")
    assert inspect(tmp_path).status == "incomplete"


def test_existing_flat_export_is_reused_without_revision_guess(tmp_path):
    root = transformer(tmp_path / "models/org--model")
    before = {p: p.stat().st_mtime_ns for p in root.iterdir()}
    result = inspect(tmp_path)
    assert result.status == "structurally_valid" and result.revision is None
    assert result.path == str(root)
    assert before == {p: p.stat().st_mtime_ns for p in root.iterdir()}
    assert inspect(tmp_path, "a" * 40).status == "missing"


def test_readonly_model_root_is_not_created_or_written(tmp_path, monkeypatch):
    root = transformer(tmp_path / "weights/org--model")
    monkeypatch.setattr(settings, "MODEL_ROOT_DIR", str(root.parent))
    monkeypatch.setattr(hf_runtime, "LOCAL_MODELS_DIR", root.parent)
    monkeypatch.setattr(hf_runtime, "DOCLING_MODELS_DIR", root.parent / "docling")
    monkeypatch.setattr(hf_runtime, "HF_CACHE_DIR", tmp_path / "runtime/hf")
    monkeypatch.setattr(hf_runtime, "TORCH_CACHE_DIR", tmp_path / "runtime/torch")
    for key in (
        "HF_HOME",
        "HF_HUB_CACHE",
        "HUGGINGFACE_HUB_CACHE",
        "TORCH_HOME",
        "DOCLING_CACHE_DIR",
    ):
        monkeypatch.setenv(key, "prior")
    original = Path.mkdir

    def guarded(path, *args, **kwargs):
        assert not path.is_relative_to(root.parent), "read-only weights were modified"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", guarded)
    hf_runtime.prepare_hf_runtime()
    assert not (root.parent / "docling").exists()
    assert os.environ["HF_HUB_CACHE"] == str(tmp_path / "runtime/hf")


@pytest.mark.parametrize("part", ["config.json", "tokenizer.json", "model.safetensors"])
def test_missing_or_empty_required_part(tmp_path, part):
    root = transformer(tmp_path / "models/org--model")
    (root / part).write_bytes(b"")
    assert not inspect(tmp_path).loadable_candidate


def test_lfs_pointer_and_truncated_weight_rejected(tmp_path):
    root = transformer(tmp_path / "models/org--model")
    (root / "model.safetensors").write_bytes(
        b"version https://git-lfs.github.com/spec/v1\noid sha256:123\n"
    )
    assert "lfs_pointer_not_weights" in inspect(tmp_path).issues
    safetensor(root / "model.safetensors", b"\0")
    assert "truncated_safetensors" in inspect(tmp_path).issues


def test_every_declared_shard_is_required(tmp_path):
    root = transformer(tmp_path / "models/org--model")
    (root / "model.safetensors").rename(root / "shard-a.safetensors")
    (root / "model.safetensors.index.json").write_text(
        json.dumps(
            {
                "weight_map": {
                    "one": "shard-a.safetensors",
                    "two": "shard-b.safetensors",
                }
            }
        )
    )
    assert inspect(tmp_path).status == "incomplete"
    safetensor(root / "shard-b.safetensors")
    assert inspect(tmp_path).status == "structurally_valid"


@pytest.mark.parametrize("name", ["../outside", "/absolute", "x\\outside", "D:outside"])
def test_unsafe_shard_reference_rejected(tmp_path, name):
    root = transformer(tmp_path / "models/org--model")
    (root / "model.safetensors.index.json").write_text(
        json.dumps({"weight_map": {"one": name}})
    )
    assert "unsafe_asset_path" in inspect(tmp_path).issues


def test_ref_main_not_alphabetic_hash_determines_active_snapshot(tmp_path):
    repo = tmp_path / "hub/models--org--model"
    a = transformer(repo / "snapshots" / ("a" * 40))
    transformer(repo / "snapshots" / ("f" * 40))
    assert inspect(tmp_path).status == "ambiguous"
    (repo / "refs").mkdir()
    (repo / "refs/main").write_text("a" * 40)
    assert inspect(tmp_path).path == str(a)
    assert inspect(tmp_path, "f" * 40).revision == "f" * 40
    (repo / "refs/main").write_text("../secret")
    assert inspect(tmp_path).status == "incomplete"


def test_bad_active_snapshot_does_not_silently_load_another_revision(tmp_path):
    repo = tmp_path / "hub/models--org--model"
    transformer(repo / "snapshots" / ("a" * 40))
    (repo / "refs").mkdir()
    (repo / "refs/main").write_text("f" * 40)
    assert inspect(tmp_path).status == "missing"


def test_hf_blob_links_allowed_but_outside_links_rejected(tmp_path):
    repo = tmp_path / "hub/models--org--model"
    root = transformer(repo / "snapshots" / ("a" * 40))
    (repo / "blobs").mkdir()
    weight = repo / "blobs/abc"
    (root / "model.safetensors").rename(weight)
    (root / "model.safetensors").symlink_to(weight)
    assert inspect(tmp_path).loadable_candidate
    (root / "model.safetensors").unlink()
    outside = tmp_path / "outside"
    safetensor(outside)
    (root / "model.safetensors").symlink_to(outside)
    assert "asset_outside_model_root" in inspect(tmp_path).issues


def test_sentence_transformer_pooling_module_must_exist(tmp_path):
    root = transformer(tmp_path / "models/org--model")
    (root / "modules.json").write_text('[{"path":""},{"path":"1_Pooling"}]')
    assert inspect(tmp_path).status == "incomplete"
    (root / "1_Pooling").mkdir()
    assert inspect(tmp_path).loadable_candidate


def test_ct2_alignment_and_pipeline_layouts_remain_distinct(tmp_path):
    root = tmp_path / "ct2"
    root.mkdir()
    (root / "config.json").write_text("{}")
    (root / "model.bin").write_bytes(b"test-fixture-not-real-weights")
    (root / "vocabulary.txt").write_text("word")
    assert inspect_directory("ct2", root).layout == "ctranslate2"
    pipe = tmp_path / "pipeline"
    pipe.mkdir()
    (pipe / "config.yaml").write_text("pipeline: requires_real_loader")
    (pipe / "model.bin").write_bytes(b"synthetic-only")
    result = inspect_directory("pipeline", pipe)
    assert result.status == "bundle_requires_loader"
    assert "component_dependencies_not_exercised" in result.issues


def test_download_receipt_pin_and_optional_full_hash(tmp_path):
    root = transformer(tmp_path / "models/org--model")
    manifest(root)
    assert inspect(tmp_path, "a" * 40).loadable_candidate
    assert not inspect(tmp_path, "f" * 40).loadable_candidate
    raw = (root / "model.safetensors").read_bytes()
    (root / "model.safetensors").write_bytes(raw[:-1] + b"x")
    assert inspect(tmp_path).loadable_candidate
    result = inspect_model(
        "org/model",
        model_root=tmp_path / "models",
        cache_root=tmp_path / "hub",
        verify_hashes=True,
    )
    assert result.issues == ("manifest_file_hash_mismatch",)
    (root / "model.safetensors").write_bytes(raw[:-2])
    assert not inspect(tmp_path).loadable_candidate


@pytest.mark.skipif(os.name == "nt", reason="Linux/WSL path boundary")
def test_windows_path_on_linux_rejected_without_creating_it():
    with pytest.raises(ValueError, match="windows_path_on_linux"):
        local_path(r"D:\Projects\models")
    assert local_path("/mnt/d/models") == Path("/mnt/d/models")


def test_setup_dry_run_does_not_contact_hub_or_create_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(init_models, "MODEL_DIR", tmp_path / "models")
    monkeypatch.setattr(init_models, "HF_CACHE_DIR", tmp_path / "hub")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "local")
    monkeypatch.setenv("EMBEDDING_MODEL", "org/model")
    monkeypatch.setattr(
        init_models, "get_remote_size", Mock(side_effect=AssertionError("network"))
    )
    monkeypatch.setattr(
        init_models, "prepare_runtime", Mock(side_effect=AssertionError("writes"))
    )
    monkeypatch.setattr("sys.argv", ["init_models", "--dry-run", "--only", "embedding"])
    assert init_models.main() == 0
    assert not list(tmp_path.iterdir())


def test_partial_directory_does_not_count_even_if_large(tmp_path, monkeypatch):
    root = tmp_path / "models/org--model"
    root.mkdir(parents=True)
    with (root / "unrelated.data").open("wb") as handle:
        handle.truncate(11 * 1024 * 1024)
    monkeypatch.setattr(init_models, "MODEL_DIR", root.parent)
    monkeypatch.setattr(init_models, "HF_CACHE_DIR", tmp_path / "hub")
    assert not init_models.is_already_downloaded("org/model")


def test_downloader_pins_checks_hashes_and_activates_without_overwriting_old(
    tmp_path, monkeypatch
):
    import sys

    source = transformer(tmp_path / "source")
    legacy = transformer(tmp_path / "models/org--model")
    original = (legacy / "model.safetensors").read_bytes()
    entries = [
        SimpleNamespace(rfilename=p.name, size=p.stat().st_size)
        for p in source.iterdir()
    ]
    info = SimpleNamespace(sha="a" * 40, siblings=entries)

    def download(**kwargs):
        assert kwargs["revision"] == "a" * 40
        target = Path(kwargs["local_dir"])
        transformer(target)
        return str(target)

    monkeypatch.setitem(
        sys.modules,
        "huggingface_hub",
        SimpleNamespace(
            HfApi=lambda: SimpleNamespace(model_info=Mock(return_value=info)),
            snapshot_download=download,
        ),
    )
    monkeypatch.setattr(init_models, "MODEL_DIR", tmp_path / "models")
    path = init_models.download_snapshot("org/model")
    assert path == legacy / ".revisions" / ("a" * 40)
    assert (legacy / "model.safetensors").read_bytes() == original
    assert inspect(tmp_path).revision == "a" * 40
    result = inspect_model(
        "org/model",
        model_root=tmp_path / "models",
        cache_root=tmp_path / "hub",
        verify_hashes=True,
    )
    assert result.status == "structurally_valid"
    assert all(
        len(entry["sha256"]) == 64
        for entry in json.loads((path / ".copilot-snapshot.json").read_text())[
            "files"
        ].values()
    )


def test_incomplete_new_download_does_not_activate_or_damage_old(tmp_path, monkeypatch):
    import sys

    legacy = transformer(tmp_path / "models/org--model")

    def incomplete(**kwargs):
        path = transformer(Path(kwargs["local_dir"]))
        (path / "model.safetensors").write_bytes(b"partial")
        return str(path)

    monkeypatch.setitem(
        sys.modules,
        "huggingface_hub",
        SimpleNamespace(
            HfApi=lambda: SimpleNamespace(
                model_info=lambda *args, **kwargs: SimpleNamespace(
                    sha="f" * 40,
                    siblings=[
                        SimpleNamespace(rfilename="model.safetensors", size=99999)
                    ],
                )
            ),
            snapshot_download=incomplete,
        ),
    )
    monkeypatch.setattr(init_models, "MODEL_DIR", tmp_path / "models")
    with pytest.raises(ValueError, match="incomplete"):
        init_models.download_snapshot("org/model")
    assert not (legacy / ".copilot-active-revision").exists()
    assert inspect(tmp_path).path == str(legacy)


def test_doctor_does_not_import_models_or_change_files(tmp_path, monkeypatch):
    for name in ("EMBEDDING_PROVIDER", "RERANKER_PROVIDER"):
        monkeypatch.setattr(settings, name, "local")
    monkeypatch.setattr(settings, "TRANSCRIPTION_PROVIDER", "local_whisperx")
    monkeypatch.setattr(settings, "PARSER_PROVIDER", "docling")
    monkeypatch.setattr(settings, "AUXILIARY_MODEL_POLICY", "local_only")
    before = set(tmp_path.rglob("*"))
    report = build_report(
        model_root=tmp_path / "weights", cache_root=tmp_path / "runtime"
    )
    assert report["preflight_passed"] is False
    assert (
        report["network_requests"]
        == report["model_calls"]
        == report["files_modified"]
        == 0
    )
    assert report["tts"]["enabled_by_policy"] is False
    assert report["acceptance"]["audio_review"] == "not_exercised"
    assert before == set(tmp_path.rglob("*"))
