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


def list_cached_models(filter_substring: str = "") -> list[str]:
    """Return human-readable HF model ids that are present locally.

    Used by error messages so "model X not found" can list what IS available
    instead of just telling the operator to download.

    Scans both lookup roots ``resolve_local_snapshot`` checks. ``filter_substring``
    narrows the result to ids containing that text (case-insensitive); pass
    e.g. ``"reranker"`` from the reranker error path to filter cleanly.
    """
    seen: set[str] = set()

    if LOCAL_MODELS_DIR.exists():
        for entry in LOCAL_MODELS_DIR.iterdir():
            if entry.is_dir() and any(entry.iterdir()):
                seen.add(entry.name.replace("--", "/"))

    if HF_CACHE_DIR.exists():
        for entry in HF_CACHE_DIR.iterdir():
            if entry.is_dir() and entry.name.startswith("models--"):
                name = entry.name.removeprefix("models--").replace("--", "/")
                # Only count it as "available" if there's an actual snapshot
                # with content; an empty cache dir is misleading.
                snap = entry / "snapshots"
                if snap.exists() and any(
                    s.is_dir() and any(c.is_file() for c in s.iterdir())
                    for s in snap.iterdir()
                ):
                    seen.add(name)

    needle = filter_substring.lower()
    return sorted(s for s in seen if not needle or needle in s.lower())


def format_missing_model_error(
    model_id: str,
    role: str,
    filter_substring: str = "",
    fix_hint: str = "",
) -> str:
    """Build a multi-line error message for a missing local model.

    Lists everything that IS in the cache (filtered to the same role family),
    so the operator can immediately see "oh I have bge-reranker-base but .env
    asked for v2-m3 — either change the env var or download v2-m3".
    """
    available = list_cached_models(filter_substring)
    lines = [
        f"{role} model '{model_id}' is not in the local cache.",
        f"  Looked in: {LOCAL_MODELS_DIR}",
        f"             {HF_CACHE_DIR}",
    ]
    if available:
        lines.append(f"  Available {role.lower()} models in cache:")
        for m in available:
            lines.append(f"    - {m}")
        lines.append("  → Either edit .env to point to one of the above,")
        lines.append("    or download the requested model.")
    else:
        lines.append(f"  (No {role.lower()} models cached at all.)")
    if fix_hint:
        lines.append(f"  Download: {fix_hint}")
    return "\n".join(lines)
