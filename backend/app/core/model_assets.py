"""Read-only checks for local weights; never download or deserialize model code.

Structural checks are not a checksum, license, GPU compatibility or inference
quality certification. Custom pipeline bundles retain an explicit loader check.
HF snapshot hashes have no chronological order: resolve refs, not sorted hashes.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

_REPO = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*(?:/[A-Za-z0-9_][A-Za-z0-9_.-]*)?$")
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_LFS_POINTER = b"version https://git-lfs.github.com/spec/v1"
_JSON_LIMIT = 8 * 1024 * 1024


@dataclass(frozen=True)
class ModelInspection:
    model_id: str
    path: str | None
    status: str
    layout: str | None = None
    revision: str | None = None
    issues: tuple[str, ...] = ()
    checked_files: tuple[str, ...] = ()

    @property
    def loadable_candidate(self) -> bool:
        return self.status in {"structurally_valid", "bundle_requires_loader"}

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def local_path(value: str | Path) -> Path:
    """Reject Windows drive strings on Linux instead of creating fake D: dirs."""
    if os.name != "nt" and PureWindowsPath(str(value)).drive:
        raise ValueError("windows_path_on_linux: use the mounted /mnt/<drive>/ path")
    return Path(value).expanduser()


def validate_model_id(model_id: str) -> None:
    if not _REPO.fullmatch(model_id) or ".." in model_id or "--" in model_id:
        raise ValueError("invalid_model_id")


def _file(root: Path, name: str, allowed_root: Path) -> Path:
    relative = PurePosixPath(name)
    if (
        not name
        or relative.is_absolute()
        or ".." in relative.parts
        or "\\" in name
        or ":" in name
    ):
        raise ValueError("unsafe_asset_path")
    target = root.joinpath(*relative.parts).resolve(strict=True)
    if not target.is_relative_to(allowed_root.resolve()) or not target.is_file():
        raise ValueError("asset_outside_model_root")
    if target.stat().st_size == 0:
        raise ValueError("empty_asset")
    with target.open("rb") as handle:
        if handle.read(len(_LFS_POINTER)) == _LFS_POINTER:
            raise ValueError("lfs_pointer_not_weights")
    return target


def _decode_json(raw: bytes) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate_asset_metadata_key")
            result[key] = value
        return result

    def invalid_constant(_value):
        raise ValueError("nonfinite_asset_metadata")

    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant)
    except RecursionError:
        raise ValueError("asset_metadata_too_deep") from None


def _check_safetensors(path: Path) -> None:
    """Check header extent and data offsets without loading tensors or pickle.

    This detects truncated downloads, not malicious/incorrect tensor values.
    Format: https://github.com/huggingface/safetensors#format
    """
    size = path.stat().st_size
    with path.open("rb") as handle:
        prefix = handle.read(8)
        length = int.from_bytes(prefix, "little")
        if len(prefix) != 8 or not 2 <= length <= _JSON_LIMIT or 8 + length > size:
            raise ValueError("invalid_safetensors_header")
        metadata = _decode_json(handle.read(length))
    if not isinstance(metadata, dict):
        raise ValueError("invalid_safetensors_header")
    spans = []
    for key, item in metadata.items():
        if key == "__metadata__":
            continue
        offsets = item.get("data_offsets") if isinstance(item, dict) else None
        if (
            not isinstance(offsets, list)
            or len(offsets) != 2
            or not all(type(x) is int for x in offsets)
        ):
            raise ValueError("invalid_safetensors_offsets")
        start, end = offsets
        if not 0 <= start <= end <= size - 8 - length:
            raise ValueError("truncated_safetensors")
        if end > start:
            spans.append((start, end))
    end = 0
    for start, stop in sorted(spans):
        if start != end:
            raise ValueError("invalid_safetensors_extent")
        end = stop
    if end != size - 8 - length:
        raise ValueError("invalid_safetensors_extent")


def _json(root: Path, name: str, allowed: Path) -> dict[str, Any]:
    target = _file(root, name, allowed)
    with target.open("rb") as handle:
        raw = handle.read(_JSON_LIMIT + 1)
    if len(raw) > _JSON_LIMIT:
        raise ValueError("asset_metadata_too_large")
    value = _decode_json(raw)
    if not isinstance(value, dict):
        raise ValueError("asset_metadata_not_object")
    return value


def inspect_directory(
    model_id: str,
    root: Path,
    *,
    allowed_root: Path | None = None,
    revision: str | None = None,
    verify_hashes: bool = False,
) -> ModelInspection:
    """Validate a recognized weight layout, including every indexed shard.

    Existing pyannote/Docling bundles are not rewritten or treated as ordinary
    Transformers models. Their local component dependencies still need their
    loader's offline smoke test, which this lightweight check does not execute.
    """
    allowed = (allowed_root or root).resolve()
    checked: list[str] = []
    layout = None

    def require(name: str) -> None:
        target = _file(root, name, allowed)
        if name.endswith(".safetensors"):
            _check_safetensors(target)
        checked.append(name)

    def require_one(names: tuple[str, ...]) -> None:
        for name in names:
            if (root / name).exists() or (root / name).is_symlink():
                require(name)
                return
        raise ValueError("missing_asset:" + "|".join(names))

    try:
        if not root.is_dir():
            return ModelInspection(model_id, str(root), "missing")
        if not root.resolve().is_relative_to(allowed):
            raise ValueError("model_directory_outside_root")
        if (root / ".copilot-snapshot.json").exists():
            manifest = _json(root, ".copilot-snapshot.json", allowed)
            if (
                manifest.get("schema_version") != 1
                or manifest.get("model_id") != model_id
            ):
                raise ValueError("invalid_snapshot_manifest")
            recorded = manifest.get("revision")
            if not isinstance(recorded, str) or not _REVISION.fullmatch(recorded):
                raise ValueError("invalid_manifest_revision")
            if revision is not None and recorded != revision:
                raise ValueError("model_revision_mismatch")
            revision = recorded
            entries = manifest.get("files")
            if not isinstance(entries, dict) or not 1 <= len(entries) <= 4096:
                raise ValueError("invalid_manifest_files")
            for name, metadata in entries.items():
                if not isinstance(metadata, dict):
                    raise ValueError("invalid_manifest_file")
                target = _file(root, name, allowed)
                size = metadata.get("size")
                digest = metadata.get("sha256")
                if type(size) is not int or size < 1 or target.stat().st_size != size:
                    raise ValueError("manifest_file_size_mismatch")
                if not isinstance(digest, str) or not re.fullmatch(
                    r"[0-9a-f]{64}", digest
                ):
                    raise ValueError("invalid_manifest_sha256")
                if verify_hashes:
                    with target.open("rb") as handle:
                        actual = hashlib.file_digest(handle, "sha256").hexdigest()
                    if actual != digest:
                        raise ValueError("manifest_file_hash_mismatch")
                checked.append(name)
        if (root / "config.json").exists():
            _json(root, "config.json", allowed)
            checked.append("config.json")
            if (root / "model.bin").exists():
                layout = "ctranslate2"
                require("model.bin")
                require_one(("tokenizer.json", "vocabulary.json", "vocabulary.txt"))
                # Whisper preprocessing is optional in some older CT2 exports;
                # real loading remains a separate acceptance stage.
            else:
                layout = "transformers"
                index_name = next(
                    (
                        name
                        for name in (
                            "model.safetensors.index.json",
                            "pytorch_model.bin.index.json",
                        )
                        if (root / name).exists()
                    ),
                    None,
                )
                if index_name:
                    index = _json(root, index_name, allowed)
                    checked.append(index_name)
                    weights = index.get("weight_map")
                    if not isinstance(weights, dict) or not weights:
                        raise ValueError("empty_weight_index")
                    if not all(isinstance(name, str) for name in weights.values()):
                        raise ValueError("invalid_weight_index")
                    for name in sorted(set(weights.values())):
                        require(name)
                else:
                    require_one(("model.safetensors", "pytorch_model.bin"))
                require_one(
                    (
                        "tokenizer.json",
                        "tokenizer.model",
                        "sentencepiece.bpe.model",
                        "spiece.model",
                        "vocab.json",
                        "vocab.txt",
                    )
                )
                modules = root / "modules.json"
                if modules.exists():
                    # SentenceTransformers modules must not point outside the snapshot.
                    target = _file(root, "modules.json", allowed)
                    with target.open("rb") as handle:
                        raw = handle.read(_JSON_LIMIT + 1)
                    if len(raw) > _JSON_LIMIT:
                        raise ValueError("asset_metadata_too_large")
                    entries = _decode_json(raw)
                    if not isinstance(entries, list) or not entries:
                        raise ValueError("invalid_sentence_transformer_modules")
                    for entry in entries:
                        folder = entry.get("path") if isinstance(entry, dict) else None
                        if (
                            not isinstance(folder, str)
                            or ".." in PurePosixPath(folder).parts
                            or "\\" in folder
                            or ":" in folder
                        ):
                            raise ValueError("unsafe_sentence_transformer_module")
                        directory = (root / folder).resolve(strict=True)
                        if (
                            not directory.is_relative_to(root.resolve())
                            or not directory.is_dir()
                        ):
                            raise ValueError("missing_sentence_transformer_module")
                    checked.append("modules.json")
        else:
            layout = "pipeline_bundle"
            configs, weights = [], []
            walked = 0
            for directory, folders, files in os.walk(root, followlinks=False):
                folders[:] = [
                    name
                    for name in folders
                    if name not in {".cache", ".git", ".revisions"}
                ]
                for name in files:
                    walked += 1
                    if walked > 4096:
                        raise ValueError("pipeline_bundle_capacity")
                    path = Path(directory) / name
                    if path.suffix in {".yaml", ".json"}:
                        configs.append(path)
                    if path.suffix in {".bin", ".safetensors", ".onnx", ".npz", ".pt"}:
                        weights.append(path)
            if not configs or not weights:
                raise ValueError("missing_pipeline_config_or_weights")
            if len(configs) + len(weights) > 4096:
                raise ValueError("pipeline_bundle_capacity")
            for path in configs + weights:
                require(path.relative_to(root).as_posix())
            return ModelInspection(
                model_id,
                str(root),
                "bundle_requires_loader",
                layout,
                revision,
                ("component_dependencies_not_exercised",),
                tuple(checked),
            )
    except (OSError, ValueError, TypeError) as exc:
        # No contents, local file excerpts or arbitrary exception text in reports.
        code = str(exc) if type(exc) is ValueError else type(exc).__name__
        return ModelInspection(
            model_id, str(root), "incomplete", layout, revision, (code,), tuple(checked)
        )
    return ModelInspection(
        model_id, str(root), "structurally_valid", layout, revision, (), tuple(checked)
    )


def inspect_model(
    model_id: str,
    *,
    model_root: Path,
    cache_root: Path,
    revision: str | None = None,
    verify_hashes: bool = False,
) -> ModelInspection:
    validate_model_id(model_id)
    if revision is not None and not _REVISION.fullmatch(revision):
        raise ValueError("model_revision_must_be_full_commit_sha")
    model_root, cache_root = local_path(model_root), local_path(cache_root)
    direct = model_root / model_id.replace("/", "--")
    repo = cache_root / f"models--{model_id.replace('/', '--')}"
    # A completed setup download activates one immutable revision atomically.
    # Interrupted upgrades cannot replace the user's existing flat export.
    pinned = revision
    active = direct / ".copilot-active-revision"
    if revision is None and (active.exists() or active.is_symlink()):
        try:
            active = _file(direct, ".copilot-active-revision", direct)
            with active.open("r", encoding="utf-8") as handle:
                revision = handle.read(128).strip()
            if not _REVISION.fullmatch(revision):
                raise ValueError("invalid_active_revision")
        except (ValueError, OSError):
            return ModelInspection(
                model_id, None, "incomplete", issues=("invalid_active_revision",)
            )
    if revision and (direct / ".revisions" / revision).is_dir():
        versioned = direct / ".revisions" / revision
        if not (versioned / ".copilot-snapshot.json").is_file():
            return ModelInspection(
                model_id, str(versioned), "incomplete", issues=("unverified_download",)
            )
        return inspect_directory(
            model_id, versioned, revision=revision, verify_hashes=verify_hashes
        )
    if active.exists() and pinned is None:
        return ModelInspection(
            model_id, None, "incomplete", issues=("active_revision_missing",)
        )
    # Explicitly pinned loads never fall back to an unversioned export.
    if direct.exists() and (
        revision is None or (direct / ".copilot-snapshot.json").exists()
    ):
        return inspect_directory(
            model_id, direct, revision=revision, verify_hashes=verify_hashes
        )
    snapshots = repo / "snapshots"
    if revision is None:
        main = repo / "refs" / "main"
        if main.exists() or main.is_symlink():
            try:
                main = _file(repo, "refs/main", repo)
            except (ValueError, OSError):
                return ModelInspection(
                    model_id, None, "incomplete", issues=("invalid_cached_ref",)
                )
            with main.open("r", encoding="utf-8") as handle:
                revision = handle.read(128).strip()
            if not _REVISION.fullmatch(revision):
                return ModelInspection(
                    model_id, None, "incomplete", issues=("invalid_cached_ref",)
                )
        elif snapshots.is_dir():
            candidates = [
                p.name
                for p in snapshots.iterdir()
                if p.is_dir() and _REVISION.fullmatch(p.name)
            ]
            if len(candidates) > 1:
                return ModelInspection(
                    model_id, None, "ambiguous", issues=("pin_revision_or_restore_ref",)
                )
            if candidates:
                revision = candidates[0]
    if revision:
        return inspect_directory(
            model_id,
            snapshots / revision,
            allowed_root=repo,
            revision=revision,
            verify_hashes=verify_hashes,
        )
    return ModelInspection(model_id, None, "missing")
