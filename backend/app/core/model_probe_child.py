"""Private stdlib-only entry point for an explicitly requested model smoke test.

Launched as ``python -I -B <this-file>`` in the chosen ML environment, not imported
into the API/Celery process. Only synthetic inputs are used. SDK offline flags
and Python audit hooks prevent ordinary network access, but are NOT an OS
sandbox against native extensions or malicious local code. Use trusted weights
and an offline/network-isolated host when stronger containment is required.
"""

from __future__ import annotations

import contextlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import time

ROLES = {"embedding", "reranking", "transcription", "alignment"}


def _no_network(event, _args):
    if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
        raise RuntimeError("offline_probe_network_denied")


def _request(raw: bytes) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate_protocol_key")
            result[key] = value
        return result

    def invalid(_value):
        raise ValueError("nonfinite_protocol_value")

    data = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
    if (
        not isinstance(data, dict)
        or set(data)
        != {"protocol_version", "request_id", "role", "model_path", "device"}
        or type(data["protocol_version"]) is not int
        or data["protocol_version"] != 1
        or not isinstance(data["request_id"], str)
        or len(data["request_id"]) != 32
        or any(c not in "0123456789abcdef" for c in data["request_id"])
        or not isinstance(data["role"], str)
        or data["role"] not in ROLES
        or data["device"] not in ("cpu", "cuda")
        or not isinstance(data["model_path"], str)
        or not Path(data["model_path"]).is_absolute()
        or not Path(data["model_path"]).is_dir()
    ):
        raise ValueError("invalid_probe_request")
    return data


def _probe(data: dict) -> dict:
    import numpy as np

    path, device, role = data["model_path"], data["device"], data["role"]
    if role == "transcription":
        from faster_whisper import WhisperModel

        model = WhisperModel(
            path,
            device=device,
            compute_type="float16" if device == "cuda" else "int8",
            local_files_only=True,
            cpu_threads=4,
            num_workers=1,
        )
        segments, _info = model.transcribe(
            np.zeros(16000, dtype=np.float32),
            language="zh",
            beam_size=1,
            vad_filter=False,
            word_timestamps=False,
        )
        # Transcription is lazy: loading or creating the generator is not a
        # successful inference test. Do not output the generated text.
        count = sum(1 for _ in segments)
        return {"backend": "ctranslate2", "segments": count}

    import torch

    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("cuda_unavailable")
    with torch.inference_mode():
        if role == "embedding":
            from sentence_transformers import SentenceTransformer

            model = SentenceTransformer(
                path, device=device, local_files_only=True, trust_remote_code=False
            )
            values = model.encode(
                ["本地模型自检 local model check"],
                batch_size=1,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            values = np.asarray(values)
            if (
                values.ndim != 2
                or values.shape[0] != 1
                or not np.isfinite(values).all()
                or np.linalg.norm(values) == 0
            ):
                raise ValueError("invalid_embedding_output")
            info = {
                "backend": "sentence_transformers",
                "dimension": int(values.shape[1]),
            }
        elif role == "reranking":
            from sentence_transformers import CrossEncoder

            model = CrossEncoder(
                path, device=device, local_files_only=True, trust_remote_code=False
            )
            values = np.asarray(
                model.predict(
                    [("本地测试", "这是本地模型测试")],
                    batch_size=1,
                    show_progress_bar=False,
                )
            )
            if values.size != 1 or not np.isfinite(values).all():
                raise ValueError("invalid_reranker_output")
            info = {"backend": "sentence_transformers", "scores": int(values.size)}
        else:
            from transformers import AutoModelForCTC, AutoProcessor

            processor = AutoProcessor.from_pretrained(
                path, local_files_only=True, trust_remote_code=False
            )
            model = (
                AutoModelForCTC.from_pretrained(
                    path, local_files_only=True, trust_remote_code=False
                )
                .to(device)
                .eval()
            )
            inputs = processor(
                np.zeros(16000, dtype=np.float32),
                sampling_rate=16000,
                return_tensors="pt",
            )
            output = model(**{k: v.to(device) for k, v in inputs.items()}).logits
            if output.numel() < 1 or not torch.isfinite(output).all().item():
                raise ValueError("invalid_alignment_logits")
            info = {"backend": "transformers_ctc", "frames": int(output.shape[1])}
        if device == "cuda":
            torch.cuda.synchronize()
    return info


def main() -> int:
    data = None
    started = time.monotonic()
    try:
        raw = sys.stdin.buffer.read(65537)
        if len(raw) > 65536:
            raise ValueError("probe_input_limit")
        data = _request(raw)
        if any(
            os.environ.get(k) != "1" for k in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")
        ):
            raise RuntimeError("offline_environment_required")
        sys.addaudithook(_no_network)
        # Keep third-party progress and prints out of the result protocol.
        with contextlib.redirect_stdout(sys.stderr):
            details = _probe(data)
        result = {"status": "passed", "details": details}
        code = 0
    except Exception as exc:
        # Never return raw exceptions, paths, sample output or arbitrary logs.
        known = {
            "cuda_unavailable",
            "offline_environment_required",
            "offline_probe_network_denied",
            "invalid_probe_request",
            "probe_input_limit",
        }
        code_name = str(exc) if str(exc) in known else "model_load_or_inference_failed"
        if isinstance(exc, ModuleNotFoundError):
            code_name = "missing_dependency"
        result = {
            "status": "failed",
            "error_type": type(exc).__name__,
            "error_code": code_name,
        }
        code = 2
    result.update(
        {
            "protocol_version": 1,
            "request_id": data["request_id"] if data else None,
            "role": data["role"] if data else None,
            "device": data["device"] if data else None,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "quality_validated": False,
            "audio_evidence_validated": False,
            "packages": {},
        }
    )
    for name in (
        "torch",
        "sentence-transformers",
        "faster-whisper",
        "ctranslate2",
        "transformers",
    ):
        try:
            result["packages"][name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            result["packages"][name] = None
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
