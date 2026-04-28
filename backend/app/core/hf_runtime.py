import os
import warnings
from pathlib import Path
from app.core.config import settings


HF_CACHE_DIR = Path(settings.CACHE_DIR) / "huggingface"
LOCAL_MODELS_DIR = Path(settings.CACHE_DIR) / "models"
TORCH_CACHE_DIR = Path(settings.CACHE_DIR) / "torch"
DEAD_PROXY_MARKERS = ("127.0.0.1:9", "localhost:9")
PROXY_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "GIT_HTTP_PROXY", "GIT_HTTPS_PROXY")


def prepare_hf_runtime() -> Path:
    HF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    LOCAL_MODELS_DIR.mkdir(parents=True, exist_ok=True)
    TORCH_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    for key in PROXY_KEYS:
        value = os.getenv(key, "")
        if any(marker in value for marker in DEAD_PROXY_MARKERS):
            os.environ.pop(key, None)

    os.environ["HF_HOME"] = str(HF_CACHE_DIR)
    os.environ["HUGGINGFACE_HUB_CACHE"] = str(HF_CACHE_DIR)
    os.environ["TORCH_HOME"] = str(TORCH_CACHE_DIR)
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

    warnings.filterwarnings(
        "ignore",
        message="Using `TRANSFORMERS_CACHE` is deprecated",
        category=FutureWarning,
    )
    warnings.filterwarnings(
        "ignore",
        category=UserWarning,
        module=r"pyannote\.audio\.core\.io",
    )
    return HF_CACHE_DIR


def resolve_local_snapshot(model_id: str) -> str | None:
    local_model_dir = LOCAL_MODELS_DIR / model_id.replace("/", "--")
    if local_model_dir.exists() and any(local_model_dir.iterdir()):
        return str(local_model_dir)

    snapshot_root = HF_CACHE_DIR / f"models--{model_id.replace('/', '--')}" / "snapshots"
    if not snapshot_root.exists():
        return None

    for snapshot_dir in sorted(snapshot_root.iterdir(), reverse=True):
        if not snapshot_dir.is_dir():
            continue
        if any(child.is_file() for child in snapshot_dir.iterdir()):
            return str(snapshot_dir)

    return None
