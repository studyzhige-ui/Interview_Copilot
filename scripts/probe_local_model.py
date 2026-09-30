"""Explicit isolated smoke test for a trusted, already-downloaded local model.

Unlike doctor_local.py this imports model libraries, loads weights, runs a small
synthetic inference and creates disposable caches. It never downloads models or
uses provider credentials. It does NOT test transcript alignment quality, the
full recorded-audio evidence pipeline, diarization or live voice performance.
Linux/WSL2 only: run it using the chosen local-ML environment via --python.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import settings  # noqa: E402
from app.core.isolated_process import IsolatedProcessError, run_isolated  # noqa: E402
from app.core.model_assets import inspect_model, local_path  # noqa: E402

ROLE_MODELS = {
    "embedding": "EMBEDDING_MODEL",
    "reranking": "RERANKER_MODEL",
    "transcription": "TRANSCRIPTION_MODEL",
    "alignment": "TRANSCRIPTION_ALIGNMENT_MODEL",
}
CHILD = ROOT / "backend/app/core/model_probe_child.py"


def probe_environment(work: Path) -> dict[str, str]:
    """An allowlist, not a secret-name denylist. Never pass the application env."""
    env = {
        k: os.environ[k]
        for k in ("PATH", "LD_LIBRARY_PATH", "CUDA_VISIBLE_DEVICES")
        if k in os.environ
    }
    env.update(
        {
            "HOME": str(work),
            "TMPDIR": str(work),
            "XDG_CACHE_HOME": str(work / "cache"),
            "HF_HOME": str(work / "hf"),
            "HF_HUB_CACHE": str(work / "hf/hub"),
            "TORCH_HOME": str(work / "torch"),
            "SENTENCE_TRANSFORMERS_HOME": str(work / "sentence_transformers"),
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1",
            "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
            "DO_NOT_TRACK": "1",
            "TOKENIZERS_PARALLELISM": "false",
            "OMP_NUM_THREADS": "4",
            "MKL_NUM_THREADS": "4",
        }
    )
    return env


def decode_result(raw: bytes, request: dict, returncode: int) -> dict:
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError("duplicate_probe_result_key")
            value[key] = item
        return value

    def invalid(_value):
        raise ValueError("nonfinite_probe_result")

    result = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
    if not isinstance(result, dict):
        raise ValueError("invalid_probe_result")
    for name in ("protocol_version", "request_id", "role", "device"):
        if (
            type(result.get(name)) is not type(request[name])
            or result.get(name) != request[name]
        ):
            raise ValueError("probe_response_identity_mismatch")
    if (
        result.get("status") not in ("passed", "failed")
        or (result["status"] == "passed") != (returncode == 0)
        or result.get("quality_validated") is not False
        or result.get("audio_evidence_validated") is not False
    ):
        raise ValueError("invalid_probe_result_status")
    # Third-party logging is never published. Pick only typed protocol fields.
    safe = {k: request[k] for k in ("protocol_version", "request_id", "role", "device")}
    safe.update(
        status=result["status"], quality_validated=False, audio_evidence_validated=False
    )
    if result["status"] == "failed":
        kind = result.get("error_type")
        if not isinstance(kind, str) or not re.fullmatch(
            r"[A-Za-z_][A-Za-z_0-9]{0,79}", kind
        ):
            raise ValueError("invalid_probe_error_type")
        safe["error_type"] = kind
        error = result.get("error_code")
        if not isinstance(error, str) or error not in {
            "cuda_unavailable",
            "offline_environment_required",
            "offline_probe_network_denied",
            "invalid_probe_request",
            "probe_input_limit",
            "missing_dependency",
            "model_load_or_inference_failed",
        }:
            raise ValueError("invalid_probe_error_code")
        safe["error_code"] = error
    else:
        details = result.get("details")
        expected = {
            "embedding": ("sentence_transformers", "dimension"),
            "reranking": ("sentence_transformers", "scores"),
            "transcription": ("ctranslate2", "segments"),
            "alignment": ("transformers_ctc", "frames"),
        }[request["role"]]
        if (
            not isinstance(details, dict)
            or details.get("backend") != expected[0]
            or type(details.get(expected[1])) is not int
            or details[expected[1]] < (0 if request["role"] == "transcription" else 1)
        ):
            raise ValueError("invalid_probe_details")
        safe["details"] = {"backend": expected[0], expected[1]: details[expected[1]]}
    packages = result.get("packages")
    if not isinstance(packages, dict):
        raise ValueError("invalid_probe_packages")
    safe["packages"] = {}
    for name in (
        "torch",
        "sentence-transformers",
        "faster-whisper",
        "ctranslate2",
        "transformers",
    ):
        value = packages.get(name)
        if value is not None and (
            not isinstance(value, str)
            or not re.fullmatch(r"[A-Za-z0-9+._-]{1,80}", value)
        ):
            raise ValueError("invalid_probe_package_version")
        safe["packages"][name] = value
    return safe


async def probe(args) -> dict:
    cache = local_path(args.cache_dir or settings.CACHE_DIR)
    model_root = local_path(
        args.model_root or settings.MODEL_ROOT_DIR or cache / "models"
    )
    model_id = args.model or getattr(settings, ROLE_MODELS[args.role])
    inspection = inspect_model(
        model_id,
        model_root=model_root,
        cache_root=cache / "huggingface",
        revision=settings.MODEL_REVISIONS_JSON.get(model_id),
        verify_hashes=args.verify_hashes,
    )
    report = {
        "scope": "isolated_local_model_smoke",
        "model": inspection.as_dict(),
        "role": args.role,
        "quality_validated": False,
        "audio_evidence_validated": False,
        "offline_boundary": "sdk_offline_flags_and_python_socket_audit_not_os_sandbox",
    }
    expected = "ctranslate2" if args.role == "transcription" else "transformers"
    if not inspection.loadable_candidate or inspection.layout != expected:
        return {
            **report,
            "status": "blocked",
            "error_code": "model_requires_supported_complete_layout",
        }
    if os.name != "posix":
        return {**report, "status": "blocked", "error_code": "use_linux_or_wsl2"}
    if cache.resolve().is_relative_to(Path(inspection.path).resolve()):
        raise ValueError("runtime_cache_must_not_be_inside_model")
    # Do not resolve the venv Python symlink: doing so loses its environment.
    executable = Path(args.python).expanduser().absolute()
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError("invalid_ml_python_executable")
    work_root = cache / "probe-runs"
    work_root.mkdir(parents=True, exist_ok=True)
    request = {
        "protocol_version": 1,
        "request_id": uuid.uuid4().hex,
        "role": args.role,
        "model_path": str(Path(inspection.path).resolve()),
        "device": args.device,
    }
    with tempfile.TemporaryDirectory(prefix="probe-", dir=work_root) as work_name:
        work = Path(work_name).resolve()
        result = await run_isolated(
            [str(executable), "-I", "-B", str(CHILD)],
            cwd=work,
            env=probe_environment(work),
            input_data=json.dumps(request).encode(),
            timeout_seconds=args.timeout,
        )
        checked = decode_result(result.stdout, request, result.returncode)
    report.update(
        checked, elapsed_seconds=round(result.elapsed_seconds, 3), process_reaped=True
    )
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=ROLE_MODELS, required=True)
    parser.add_argument(
        "--model", help="Defaults to the selected role's configured model"
    )
    parser.add_argument("--model-root")
    parser.add_argument("--cache-dir")
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python executable in the local ML environment",
    )
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--verify-hashes", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = asyncio.run(probe(args))
    except IsolatedProcessError as exc:
        report = {
            "status": "failed",
            "error_code": str(exc),
            "quality_validated": False,
        }
    except (ValueError, OSError, RecursionError):
        report = {
            "status": "failed",
            "error_code": "invalid_probe_configuration_or_response",
            "quality_validated": False,
        }
    except KeyboardInterrupt:
        report = {"status": "cancelled", "quality_validated": False}
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
