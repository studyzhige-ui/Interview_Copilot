import os
import warnings
from pathlib import Path

from app.core.config import settings
from app.core.model_assets import inspect_model, local_path

HF_CACHE_DIR = local_path(settings.CACHE_DIR) / "huggingface"
LOCAL_MODELS_DIR = (
    local_path(settings.MODEL_ROOT_DIR)
    if settings.MODEL_ROOT_DIR
    else local_path(settings.CACHE_DIR) / "models"
)
TORCH_CACHE_DIR = local_path(settings.CACHE_DIR) / "torch"
# Docling uses its own artifact layout, but its weights still belong in the
# single application-managed model directory.
DOCLING_MODELS_DIR = LOCAL_MODELS_DIR / "docling"
DEAD_PROXY_MARKERS = ("127.0.0.1:9", "localhost:9")
PROXY_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "GIT_HTTP_PROXY",
    "GIT_HTTPS_PROXY",
)


def prepare_hf_runtime() -> Path:
    HF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if not settings.MODEL_ROOT_DIR:
        LOCAL_MODELS_DIR.mkdir(parents=True, exist_ok=True)
    TORCH_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # Never create or modify a configured shared/read-only model root.

    for key in PROXY_KEYS:
        value = os.getenv(key, "")
        if any(marker in value for marker in DEAD_PROXY_MARKERS):
            os.environ.pop(key, None)

    os.environ["HF_HOME"] = str(HF_CACHE_DIR)
    os.environ["HUGGINGFACE_HUB_CACHE"] = str(HF_CACHE_DIR)
    os.environ["HF_HUB_CACHE"] = str(HF_CACHE_DIR)
    os.environ["TORCH_HOME"] = str(TORCH_CACHE_DIR)
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    if settings.LOCAL_MODELS_OFFLINE or settings.AUXILIARY_MODEL_POLICY == "local_only":
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
    # Docling reads this through its DOCLING_ settings prefix. The parser also
    # passes artifacts_path explicitly so imports cannot redirect downloads to
    # a user-profile cache.
    os.environ["DOCLING_CACHE_DIR"] = str(DOCLING_MODELS_DIR)

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


def inspect_local_model(model_id: str):
    return inspect_model(
        model_id,
        model_root=LOCAL_MODELS_DIR,
        cache_root=HF_CACHE_DIR,
        revision=settings.MODEL_REVISIONS_JSON.get(model_id),
    )


def resolve_local_snapshot(model_id: str) -> str | None:
    """Resolve verified structure, not an arbitrary/nonempty HF snapshot.

    Pipeline bundles still require an offline loader test. This function neither
    downloads nor certifies model accuracy, revision provenance or GPU support.
    """
    report = inspect_local_model(model_id)
    return report.path if report.loadable_candidate else None


def list_cached_models(filter_substring: str = "") -> list[str]:
    """Return recognized loadable candidates; incomplete directories stay out."""
    seen: set[str] = set()
    for root, prefix in ((LOCAL_MODELS_DIR, ""), (HF_CACHE_DIR, "models--")):
        if not root.is_dir():
            continue
        for entry in root.iterdir():
            if not entry.is_dir() or entry.name == "docling":
                continue
            if prefix and not entry.name.startswith(prefix):
                continue
            if not prefix and "--" not in entry.name:
                continue
            model_id = entry.name.removeprefix(prefix).replace("--", "/")
            if filter_substring.lower() not in model_id.lower():
                continue
            try:
                if inspect_local_model(model_id).loadable_candidate:
                    seen.add(model_id)
            except (ValueError, OSError):
                continue
    return sorted(seen)


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
    report = inspect_local_model(model_id)
    lines = [
        f"{role} model '{model_id}' is not in the local cache.",
        f"  Status: {report.status}; issues: {', '.join(report.issues)}",
        f"  Looked in: {LOCAL_MODELS_DIR}",
        f"             {HF_CACHE_DIR}",
    ]
    if available:
        lines.append(
            f"  Structurally available {role.lower()} candidates (not inference-tested):"
        )
        for m in available:
            lines.append(f"    - {m}")
        lines.append("  → Either edit .env to point to one of the above,")
        lines.append("    or download the requested model.")
    else:
        lines.append(f"  (No {role.lower()} models cached at all.)")
    if fix_hint:
        lines.append(f"  Download: {fix_hint}")
    return "\n".join(lines)
