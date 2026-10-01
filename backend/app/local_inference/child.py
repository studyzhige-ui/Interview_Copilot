"""Fresh, credential-free ML interpreter. Only the broker starts this file.

SDK offline flags are a download guard, NOT a sandbox for native/model code.
Use trusted local weights. This process never receives a database or API key.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path
import sys

# -I excludes caller PYTHONPATH and the current working directory. Add only this
# source package so the same protocol is used by API, broker and child.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.local_inference.config import ModelSpec  # noqa: E402
from app.local_inference.protocol import (  # noqa: E402
    frame,
    read_sync,
    request,
    validate_values,
)


class InputTooLong(ValueError):
    pass


def load_model(spec):
    if spec.role == "synthesis":
        from app.local_inference.qwen_synthesis import load

        return load(spec)
    if spec.role == "diarization":
        from app.local_inference.pyannote_audio import load

        return load(spec)
    if spec.role in {"transcription", "alignment"}:
        from app.local_inference.qwen_audio import load

        return load(spec)
    import torch
    from sentence_transformers import CrossEncoder, SentenceTransformer

    torch.set_num_threads(4)
    if spec.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("cuda_unavailable")
    common = dict(device=spec.device, local_files_only=True, trust_remote_code=False)
    if spec.role == "embedding":
        model = SentenceTransformer(spec.model_path, **common)
        if model.get_sentence_embedding_dimension() != spec.dimension:
            raise ValueError("model_dimension_mismatch")
        if model.max_seq_length < spec.max_tokens:
            raise ValueError("configured_tokens_exceed_model_capacity")
        model.max_seq_length = spec.max_tokens
    else:
        model = CrossEncoder(spec.model_path, max_length=spec.max_tokens, **common)
    return model


def infer(model, spec, task):
    import torch

    if task["binding"] != spec.binding or task["role"] != spec.role:
        raise ValueError("model_binding_mismatch")
    if spec.role in {"transcription", "alignment"}:
        from app.local_inference.qwen_audio import infer as infer_audio

        return infer_audio(model, spec, task)
    if spec.role == "diarization":
        from app.local_inference.pyannote_audio import infer as infer_speakers

        return infer_speakers(model, spec, task)
    if spec.role == "synthesis":
        from app.local_inference.qwen_synthesis import infer as infer_synthesis

        return infer_synthesis(model, spec, task)
    texts = task["texts"]
    with torch.inference_mode():
        if spec.role == "embedding":
            prefix = (
                spec.query_prefix if task["operation"] == "query" else spec.text_prefix
            )
            rendered = [prefix + text for text in texts]
            lengths = model.tokenizer(
                rendered, truncation=False, add_special_tokens=True
            )["input_ids"]
            if any(len(row) > spec.max_tokens for row in lengths):
                raise InputTooLong("input_exceeds_model_tokens")
            result = model.encode(
                texts,
                prompt=prefix,
                batch_size=8,
                normalize_embeddings=True,
                show_progress_bar=False,
                convert_to_numpy=True,
            ).tolist()
        else:
            query = task["query"]
            lengths = model.tokenizer(
                [query] * len(texts), texts, truncation=False, add_special_tokens=True
            )["input_ids"]
            if any(len(row) > spec.max_tokens for row in lengths):
                raise InputTooLong("input_exceeds_model_tokens")
            result = model.predict(
                [(query, text) for text in texts],
                batch_size=8,
                show_progress_bar=False,
                convert_to_numpy=True,
            ).tolist()
        if spec.device == "cuda":
            # Completion is not just asynchronous kernel submission.
            torch.cuda.synchronize()
    return validate_values(
        result, role=spec.role, count=len(texts), dimension=spec.dimension
    )


def _deny_network(event, _args):
    if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
        raise RuntimeError("local_inference_network_denied")


def bind_parent():
    """Terminate a Linux ML child if its broker disappears, including SIGKILL.

    The before/after checks close the race between spawn, adoption and prctl.
    This covers this direct model process, not arbitrary plugin grandchildren.
    """
    import ctypes
    import signal

    expected = int(os.environ["COPILOT_BROKER_PID"])
    if os.getppid() != expected:
        raise RuntimeError("broker_parent_lost")
    libc = ctypes.CDLL(None, use_errno=True)
    libc.prctl.argtypes = [
        ctypes.c_int,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
    ]
    libc.prctl.restype = ctypes.c_int
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
        raise OSError(ctypes.get_errno(), "parent_death_signal_unavailable")
    if os.getppid() != expected:
        raise RuntimeError("broker_parent_lost")


def main():
    bind_parent()
    # Even native stdout writes are redirected away from the protocol descriptor.
    wire = os.fdopen(os.dup(sys.stdout.fileno()), "wb", buffering=0)
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    sys.addaudithook(_deny_network)
    try:
        with contextlib.redirect_stdout(sys.stderr):
            spec = ModelSpec(**read_sync(sys.stdin.buffer))
            model = load_model(spec)
        wire.write(frame({"status": "ready", "binding": spec.binding}))
    except Exception:
        wire.write(frame({"status": "load_failed"}))
        return 2
    while True:
        try:
            task = request(read_sync(sys.stdin.buffer))
        except EOFError:
            return 0
        except Exception:
            return 2
        try:
            with contextlib.redirect_stdout(sys.stderr):
                values = infer(model, spec, task)
            wire.write(
                frame(
                    {
                        "id": task["id"],
                        "binding": spec.binding,
                        "status": "completed",
                        "values": values,
                    }
                )
            )
        except InputTooLong:
            wire.write(
                frame(
                    {
                        "id": task["id"],
                        "binding": spec.binding,
                        "status": "rejected",
                        "code": "input_exceeds_model_tokens",
                    }
                )
            )
        except Exception:
            # Never put a model exception (which can contain input text) on wire.
            wire.write(
                frame(
                    {
                        "id": task["id"],
                        "binding": spec.binding,
                        "status": "failed",
                        "code": "model_inference_failed",
                    }
                )
            )
            return 2


if __name__ == "__main__":
    raise SystemExit(main())
