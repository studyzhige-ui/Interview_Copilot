"""Prepare (never download) explicit local RAG broker configuration."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import settings  # noqa: E402
from app.core.model_assets import inspect_model, local_path  # noqa: E402
from app.local_inference.config import BrokerConfig, ModelSpec  # noqa: E402
from app.local_inference.server import private_directory  # noqa: E402


def build_config(
    *,
    python: str,
    device: str,
    runtime_dir: Path,
    model_root: Path,
    cache_root: Path,
    capacity_mib: int = 12000,
) -> BrokerConfig:
    if not sys.platform.startswith("linux"):
        raise ValueError("use_linux_or_wsl2")
    executable = Path(python).expanduser().absolute()  # Preserve the venv symlink.
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError("invalid_ml_python")
    specs = []
    for role, model_id, dim, tokens, reservation in (
        (
            "embedding",
            settings.EMBEDDING_MODEL,
            settings.EMBEDDING_DIM,
            settings.LOCAL_EMBED_MAX_TOKENS,
            5000,
        ),
        (
            "reranking",
            settings.RERANKER_MODEL,
            1,
            settings.RAG_RERANK_INPUT_TOKENS,
            3000,
        ),
    ):
        revision = settings.MODEL_REVISIONS_JSON.get(model_id)
        asset = inspect_model(
            model_id,
            model_root=model_root,
            cache_root=cache_root / "huggingface",
            revision=revision,
            verify_hashes=True,
        )
        if not asset.loadable_candidate or asset.layout != "transformers":
            raise ValueError(f"{role}_requires_complete_local_weights")
        specs.append(
            ModelSpec(
                role,
                model_id,
                asset.path,
                str(executable),
                device=device,
                revision=revision,
                dimension=dim,
                max_tokens=tokens,
                reservation_mib=reservation,
                query_prefix=settings.LOCAL_EMBED_QUERY_PREFIX
                if role == "embedding"
                else "",
                text_prefix=settings.LOCAL_EMBED_TEXT_PREFIX
                if role == "embedding"
                else "",
            )
        )
    return BrokerConfig(
        str(runtime_dir / "worker.sock"),
        str(runtime_dir / "cache"),
        tuple(specs),
        capacity_mib=capacity_mib,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), required=True)
    parser.add_argument("--runtime-dir", required=True)
    parser.add_argument("--model-root")
    parser.add_argument("--capacity-mib", type=int, default=12000)
    args = parser.parse_args(argv)
    runtime_dir = local_path(args.runtime_dir).absolute()
    cache = local_path(settings.CACHE_DIR).absolute()
    config = build_config(
        python=args.python,
        device=args.device,
        runtime_dir=runtime_dir,
        model_root=local_path(
            args.model_root or settings.MODEL_ROOT_DIR or cache / "models"
        ).absolute(),
        cache_root=cache,
        capacity_mib=args.capacity_mib,
    )
    private_directory(runtime_dir)
    target = runtime_dir / "config.json"
    # Refuse overwrite; an existing live daemon's identity must not change silently.
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as file:
        json.dump(config.as_dict(), file, ensure_ascii=False, indent=2)
        file.flush()
        os.fsync(file.fileno())
    print(
        json.dumps(
            {
                "config": str(target),
                "LOCAL_INFERENCE_SOCKET": config.socket_path,
                "models_checked": True,
                "gpu_validated": False,
                "quality_validated": False,
            }
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, TypeError):
        print('{"status":"blocked","code":"invalid_or_existing_local_configuration"}')
        raise SystemExit(2)
