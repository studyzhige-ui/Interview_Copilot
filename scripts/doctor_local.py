"""Read-only local-model preflight. No network, downloads, inference or secret dump.

Run from the repository root with the normal backend environment. Read-only
Windows weights may be mounted into WSL separately from writable framework
caches. A successful preflight does NOT certify GPU or audio pipeline readiness.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import settings  # noqa: E402
from app.core.model_assets import inspect_directory, inspect_model, local_path  # noqa: E402


def _disk(path: Path) -> dict:
    current = path
    while not current.exists() and current.parent != current:
        current = current.parent
    try:
        stats = shutil.disk_usage(current)
        return {"free_bytes": stats.free, "total_bytes": stats.total}
    except OSError as exc:
        return {"status": "unavailable", "error_type": type(exc).__name__}


def _package(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _detector_asset(path: str, digest: str, verify: bool) -> dict:
    """Inspect operator-selected CPU assets without importing ONNX or a model."""
    if (
        not path
        or not Path(path).is_absolute()
        or not re.fullmatch(r"[a-f0-9]{64}", digest)
    ):
        return {"status": "detector_not_configured", "loader_verified": False}
    try:
        target = Path(path)
        if not target.is_file() or not 0 < target.stat().st_size <= 64 * 1024**2:
            return {"status": "detector_file_invalid", "loader_verified": False}
        if not verify:
            return {
                "status": "detector_file_present",
                "hash_verification": "not_verified",
                "loader_verified": False,
            }
        checksum = hashlib.sha256()
        total = 0
        with target.open("rb") as source:
            while block := source.read(1024 * 1024):
                total += len(block)
                if total > 64 * 1024**2:
                    return {"status": "detector_file_invalid", "loader_verified": False}
                checksum.update(block)
        return {
            "status": "detector_hash_verified"
            if checksum.hexdigest() == digest
            else "detector_hash_mismatch",
            "loader_verified": False,
        }
    except OSError:
        return {"status": "detector_file_unavailable", "loader_verified": False}


def build_report(
    *, model_root: Path, cache_root: Path, verify_hashes: bool = False
) -> dict:
    models = []
    local_asr = settings.TRANSCRIPTION_PROVIDER in {"local_whisperx", "local_qwen_asr"}
    local_tts = settings.TTS_PROVIDER == "local_qwen3_tts"
    roles = [
        ("embedding", settings.EMBEDDING_MODEL, settings.EMBEDDING_PROVIDER == "local"),
        ("reranking", settings.RERANKER_MODEL, settings.RERANKER_PROVIDER == "local"),
        (
            "transcription",
            settings.TRANSCRIPTION_MODEL,
            local_asr,
        ),
        (
            "alignment",
            settings.TRANSCRIPTION_ALIGNMENT_MODEL,
            local_asr,
        ),
        (
            "diarization",
            settings.DIARIZATION_MODEL_ID,
            settings.DIARIZATION_MODE != "none"
            and (local_asr or settings.DIARIZATION_MODE == "pyannote"),
        ),
        ("synthesis", settings.TTS_MODEL, local_tts),
    ]
    policy_conflicts = []
    for role, model, local in roles:
        if not local:
            models.append(
                {"role": role, "model_id": model, "status": "not_selected_local"}
            )
            if (
                role in {"embedding", "reranking", "transcription", "synthesis"}
                and settings.AUXILIARY_MODEL_POLICY == "local_only"
            ):
                policy_conflicts.append(role)
            continue
        report = inspect_model(
            model,
            model_root=model_root,
            cache_root=cache_root / "huggingface",
            revision=settings.MODEL_REVISIONS_JSON.get(model),
            verify_hashes=verify_hashes,
        )
        item = {"role": role, **report.as_dict(), "loader_verified": False}
        item["hash_verification"] = (
            "checked_manifest_files"
            if verify_hashes
            and report.path
            and (Path(report.path) / ".copilot-snapshot.json").is_file()
            and report.loadable_candidate
            else "not_verified"
        )
        if role == "synthesis" and report.path:
            codec = Path(report.path) / "speech_tokenizer"
            weights = list(codec.glob("*.safetensors"))
            required = {
                "speech_tokenizer/config.json",
                *(f"speech_tokenizer/{w.name}" for w in weights),
            }
            codec_present = (codec / "config.json").is_file() and bool(weights)
            item["codec_present"] = codec_present
            item["codec_hashes_verified"] = (
                verify_hashes
                and codec_present
                and required <= set(report.checked_files)
            )
            if not codec_present or (
                verify_hashes and not item["codec_hashes_verified"]
            ):
                item["status"] = "tts_codec_missing_or_unverified"
        models.append(item)
    if settings.PARSER_PROVIDER == "docling":
        report = inspect_directory("docling", model_root / "docling")
        models.append(
            {"role": "document_parsing", **report.as_dict(), "loader_verified": False}
        )
    elif (
        settings.PARSER_PROVIDER == "llamaparse"
        and settings.AUXILIARY_MODEL_POLICY == "local_only"
    ):
        policy_conflicts.append("document_parsing")
    from app.media.realtime.config import config as realtime_config

    realtime = {
        "enabled": realtime_config.enabled,
        "native_model_streaming": "not_implemented",
        "detectors": [],
    }
    if realtime_config.enabled:
        for role, path, digest in (
            ("realtime_vad", realtime_config.vad_path, realtime_config.vad_sha256),
            ("realtime_turn", realtime_config.turn_path, realtime_config.turn_sha256),
        ):
            item = {"role": role, **_detector_asset(path, digest, verify_hashes)}
            realtime["detectors"].append(item)
            models.append(item)
    missing = [
        row["role"]
        for row in models
        if row["status"]
        not in {
            "structurally_valid",
            "bundle_requires_loader",
            "not_selected_local",
            "detector_file_present",
            "detector_hash_verified",
        }
    ]
    return {
        "schema_version": 1,
        "scope": "local_read_only_preflight",
        "network_requests": 0,
        "model_calls": 0,
        "files_modified": 0,
        "system": {
            "platform": platform.system(),
            "python": platform.python_version(),
            "wsl": "microsoft" in platform.release().lower(),
        },
        "roots": {"model_root": str(model_root), "cache_root": str(cache_root)},
        "disk": {"models": _disk(model_root), "cache": _disk(cache_root)},
        "packages": {
            name: _package(name)
            for name in (
                "torch",
                "transformers",
                "huggingface-hub",
                "whisperx",
                "docling",
            )
        },
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "policy": {
            "auxiliary_models": settings.AUXILIARY_MODEL_POLICY,
            "hf_offline": settings.LOCAL_MODELS_OFFLINE
            or settings.AUXILIARY_MODEL_POLICY == "local_only",
            "conflicts": policy_conflicts,
        },
        "models": models,
        "preflight_passed": not missing and not policy_conflicts,
        "missing_or_incomplete_roles": missing,
        "acceptance": {
            "gpu_inference": "not_exercised",
            "microphone": "not_exercised",
            "audio_review": "not_exercised",
            "model_quality": "not_exercised",
            "note": "Pipeline bundles require their real offline loader; metadata is not inference evidence.",
        },
        "tts": {
            "adapter": settings.TTS_PROVIDER,
            "local": local_tts,
            "enabled_by_policy": local_tts
            or settings.AUXILIARY_MODEL_POLICY != "local_only",
            "note": "Finite local synthesis and its codec require explicit broker preparation; generation is not playback or model-quality acceptance.",
        },
        "document_runtime": {
            "selected": settings.PARSER_PROVIDER == "docling",
            "device": "cpu",
            "isolated": True,
            "separate_interpreter_configured": bool(settings.PARSER_LOCAL_PYTHON),
            "timeout_seconds": settings.PARSER_TIMEOUT_SECONDS,
            "max_pages": settings.PARSER_MAX_PAGES,
            "loader_verified": False,
            "note": "Docling runs in an owned CPU interpreter with offline guards. RAG_DEVICE does not grant it GPU memory; actual OCR/model loading is not exercised here.",
        },
        "realtime": realtime,
        "runtime": {
            "broker_connection": "not_exercised",
            "isolated_interpreters": "not_exercised",
            "note": "Package versions describe this interpreter only; preflight_passed checks selected asset structure/policy, not runtime readiness.",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-root", default=None)
    parser.add_argument("--cache-dir", default=None)
    parser.add_argument(
        "--verify-hashes",
        action="store_true",
        help="Read complete files against a setup manifest; potentially expensive",
    )
    parser.add_argument(
        "--probe-gpu",
        action="store_true",
        help="Read nvidia-smi only; does not load Torch or run inference",
    )
    args = parser.parse_args()
    try:
        cache = local_path(args.cache_dir or settings.CACHE_DIR)
        models = local_path(
            args.model_root or settings.MODEL_ROOT_DIR or cache / "models"
        )
        report = build_report(
            model_root=models, cache_root=cache, verify_hashes=args.verify_hashes
        )
        if args.probe_gpu:
            binary = shutil.which("nvidia-smi")
            if binary:
                try:
                    result = subprocess.run(
                        [
                            binary,
                            "--query-gpu=name,driver_version,memory.total,memory.used",
                            "--format=csv,noheader,nounits",
                        ],
                        capture_output=True,
                        text=True,
                        timeout=10,
                        check=True,
                        env={
                            k: v
                            for k, v in os.environ.items()
                            if k
                            in {"PATH", "SystemRoot", "SYSTEMROOT", "LD_LIBRARY_PATH"}
                        },
                    )
                    report["gpu_probe"] = {
                        "status": "reported",
                        "csv": result.stdout[:4096],
                    }
                except (OSError, subprocess.SubprocessError) as exc:
                    report["gpu_probe"] = {
                        "status": "failed",
                        "error_type": type(exc).__name__,
                    }
            else:
                report["gpu_probe"] = {"status": "nvidia_smi_not_found"}
    except (ValueError, OSError) as exc:
        report = {
            "schema_version": 1,
            "preflight_passed": False,
            "error_code": str(exc) if type(exc) is ValueError else type(exc).__name__,
            "network_requests": 0,
            "model_calls": 0,
            "files_modified": 0,
        }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["preflight_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
