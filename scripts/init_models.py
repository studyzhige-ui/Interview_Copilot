"""Download local models for Interview Copilot.

Reads model IDs from environment variables (or .env file) and downloads them
from HuggingFace. Supports selective downloading via --only flag.

Usage:
    python scripts/init_models.py              # Interactive model/profile wizard
    python scripts/init_models.py --only embedding  # Download embedding model only
    python scripts/init_models.py --dry-run    # Show what would be downloaded

Model weights are stored under data/cache/models/. Library metadata and
temporary download state stay under data/cache/ as well.
"""

import argparse
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from huggingface_hub import snapshot_download


ROOT_DIR = Path(__file__).resolve().parents[1]
SOURCE_ROOT = (
    ROOT_DIR / "backend" if (ROOT_DIR / "backend" / "app").is_dir() else ROOT_DIR
)
sys.path.insert(0, str(SOURCE_ROOT))
load_dotenv(ROOT_DIR / ".env")

from app.core.config import settings  # noqa: E402
from app.core.hf_runtime import (  # noqa: E402
    DOCLING_MODELS_DIR,
    HF_CACHE_DIR,
    LOCAL_MODELS_DIR,
    prepare_hf_runtime,
)

MODEL_DIR = LOCAL_MODELS_DIR
ENV_FILE = ROOT_DIR / ".env"
DEFAULT_HF_ENDPOINT = "https://hf-mirror.com"

LOCAL_MODEL_CHOICES = {
    "embedding": (
        ("BAAI/bge-m3", "multilingual, recommended", "1024"),
        ("BAAI/bge-large-zh-v1.5", "Chinese, higher quality", "1024"),
        ("BAAI/bge-small-en-v1.5", "English, lightweight", "384"),
    ),
    "reranker": (
        ("BAAI/bge-reranker-v2-m3", "multilingual, recommended", None),
        ("BAAI/bge-reranker-large", "larger legacy model", None),
    ),
    "whisper": (
        (
            "deepdml/faster-whisper-large-v3-turbo-ct2",
            "multilingual turbo, recommended",
            None,
        ),
        ("Systran/faster-whisper-medium", "balanced", None),
        ("Systran/faster-whisper-small", "lightweight", None),
    ),
    "diarization": (
        (
            "pyannote-community/speaker-diarization-community-1",
            "community model, recommended",
            None,
        ),
        (
            "pyannote/speaker-diarization-3.1",
            "requires HF token and license acceptance",
            None,
        ),
    ),
}

RECOMMENDED_LOCAL_CONFIG = {
    "EMBEDDING_PROVIDER": "local",
    "EMBEDDING_MODEL": LOCAL_MODEL_CHOICES["embedding"][0][0],
    "EMBEDDING_DIM": LOCAL_MODEL_CHOICES["embedding"][0][2],
    "RERANKER_PROVIDER": "local",
    "RERANKER_MODEL": LOCAL_MODEL_CHOICES["reranker"][0][0],
    "TRANSCRIPTION_PROVIDER": "local_whisperx",
    "TRANSCRIPTION_MODEL": LOCAL_MODEL_CHOICES["whisper"][0][0],
    "DIARIZATION_MODE": "auto",
    "DIARIZATION_MODEL_ID": LOCAL_MODEL_CHOICES["diarization"][0][0],
    "PARSER_PROVIDER": "docling",
}

# Downloads use ``huggingface_hub.snapshot_download`` for every role — no
# per-role filename lists, no special-case downloaders. snapshot_download
# already handles the things we care about:
#
#   * Resume: if an earlier run was interrupted mid-file, the next call
#     picks up from the byte offset (HTTP Range request) and skips files
#     that are already complete.
#   * Concurrency: ``max_workers`` parallelism, configurable below.
#   * Repo-shape changes: when a vendor adds / renames / reformats a
#     file (e.g. faster-whisper v3 swapped ``vocabulary.txt`` for
#     ``vocabulary.json`` and added ``preprocessor_config.json``), we just
#     get the new file automatically — no code change needed.

# ── Community local-model defaults ─────────────────────────────────────

# Environment variable → default model name. These names match
# backend/app/core/config.py exactly.
MODEL_DEFAULTS = {
    "EMBEDDING_MODEL": settings.EMBEDDING_MODEL,
    "RERANKER_MODEL": settings.RERANKER_MODEL,
    "TRANSCRIPTION_MODEL": settings.TRANSCRIPTION_MODEL,
    "DIARIZATION_MODEL_ID": settings.DIARIZATION_MODEL_ID,
}

ROLE_ENV_KEYS = {
    "embedding": ("EMBEDDING_MODEL", "EMBEDDING_PROVIDER", "local"),
    "reranker": ("RERANKER_MODEL", "RERANKER_PROVIDER", "local"),
    "whisper": (
        "TRANSCRIPTION_MODEL",
        "TRANSCRIPTION_PROVIDER",
        "local_whisperx",
    ),
    "diarization": ("DIARIZATION_MODEL_ID", "DIARIZATION_MODE", "auto"),
}

# ── Size lookup: query HuggingFace live; no hardcoded fallback ───────────
#
# Old version kept a hand-maintained SIZE_ESTIMATES table — every time HF
# released a new model variant (e.g. large-v3) we'd print "unknown size"
# until someone updated the table. Now we ask HF directly via the
# `HfApi.model_info(..., files_metadata=True)` call and sum every file
# in the repo (matches what ``snapshot_download`` will pull).
#
# Costs ~0.5-2s per repo (one HTTPS HEAD per repo). For a 4-role dry-run
# that's ~3-8s, which is fine. Cached after the first call within one run.


def _humanize_bytes(n: float) -> str:
    """Format a byte count as ~X.YZ {KB|MB|GB|...}, matching the old table style."""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"~{n:.2f} {unit}"
        n /= 1024
    return f"~{n:.2f} TB"


_size_cache: dict[str, str] = {}


def get_remote_size(repo_id: str) -> str:
    """Sum the byte sizes of every file in ``repo_id`` (live HF API call).

    Returns a human-readable string like ``~1.08 GB``, or a short diagnostic
    when the API is unreachable (so dry-run still prints something useful
    rather than crashing).
    """
    if repo_id in _size_cache:
        return _size_cache[repo_id]
    try:
        from huggingface_hub import HfApi

        info = HfApi().model_info(repo_id, files_metadata=True)
        total = sum(s.size or 0 for s in info.siblings)
        result = _humanize_bytes(total) if total > 0 else "size unknown"
    except Exception as exc:
        result = f"size unavailable ({type(exc).__name__})"
    _size_cache[repo_id] = result
    return result


def repo_dir(repo_id: str) -> Path:
    return MODEL_DIR / repo_id.replace("/", "--")


def prepare_runtime(hf_endpoint: str) -> None:
    prepare_hf_runtime()
    os.environ["HF_ENDPOINT"] = hf_endpoint


def download_snapshot(repo_id: str) -> Path:
    target_dir = repo_dir(repo_id)
    path = snapshot_download(
        repo_id=repo_id,
        local_dir=str(target_dir),
        max_workers=2,
    )
    return Path(path)


_MIN_DOWNLOADED_BYTES = 10 * 1024 * 1024  # 10 MB — bigger than any config-only stub


def _tree_size(path: Path) -> int:
    """Total size of all regular files under ``path``, following symlinks."""
    total = 0
    for entry in path.rglob("*"):
        try:
            real = entry.resolve()
            if real.is_file():
                total += real.stat().st_size
        except (OSError, FileNotFoundError):
            continue
    return total


def is_already_downloaded(repo_id: str) -> bool:
    """Check if a model is fully present locally.

    Single rule for every role: the target directory's total file size must
    clear ``_MIN_DOWNLOADED_BYTES`` (10 MB). That threshold:

      * passes genuine small models (pyannote diarization ~32 MB across subdirs)
      * fails config-only stubs from interrupted downloads (a few KB)
      * is well below the smallest real model weight, so no false negatives

    Re-running ``init_models.py`` after a partial download is safe — the
    underlying ``snapshot_download`` resumes byte-by-byte where it stopped.
    """
    target = repo_dir(repo_id)
    if target.exists() and _tree_size(target) >= _MIN_DOWNLOADED_BYTES:
        return True
    # Fall back to the HF hub cache layout (snapshot_download default).
    snapshot_root = HF_CACHE_DIR / f"models--{repo_id.replace('/', '--')}" / "snapshots"
    if snapshot_root.exists() and _tree_size(snapshot_root) >= _MIN_DOWNLOADED_BYTES:
        return True
    return False


def is_docling_downloaded() -> bool:
    return _tree_size(DOCLING_MODELS_DIR) >= _MIN_DOWNLOADED_BYTES


def download_docling_models() -> Path:
    from docling.utils.model_downloader import download_models

    return Path(
        download_models(
            output_dir=DOCLING_MODELS_DIR,
            progress=True,
        )
    )


def _provider_status(role: str) -> tuple[bool, str, str]:
    """Inspect the relevant *_PROVIDER env var to decide whether the role needs a local download.

    Returns ``(needs_download, provider_id, reason)`` for nice CLI output.
    """
    if role == "embedding":
        pid = (os.getenv("EMBEDDING_PROVIDER") or "local").strip().lower()
        local = pid == "local"
    elif role == "reranker":
        pid = (os.getenv("RERANKER_PROVIDER") or "local").strip().lower()
        local = pid == "local"
    elif role in ("whisper", "diarization"):
        # Whisper + Pyannote share one toggle: TRANSCRIPTION_PROVIDER. The
        # local provider uses both; remote providers use neither (unless
        # DIARIZATION_MODE=pyannote forces local Pyannote in hybrid mode —
        # only then does diarization stay local even with remote ASR).
        pid = (os.getenv("TRANSCRIPTION_PROVIDER") or "local_whisperx").strip().lower()
        local = pid == "local_whisperx"
        if role == "diarization" and not local:
            diar_mode = (os.getenv("DIARIZATION_MODE") or "auto").strip().lower()
            if diar_mode == "pyannote":
                local = True
                pid = f"{pid} + DIARIZATION_MODE=pyannote (hybrid)"
    else:
        return True, "(unknown role)", ""
    reason = f"provider {pid!r} → " + (
        "download local copy" if local else "remote, skip"
    )
    return local, pid, reason


def _choice(prompt: str, maximum: int, default: int = 1) -> int:
    while True:
        raw = input(f"{prompt} [{default}]: ").strip()
        if not raw:
            return default
        if raw.isdigit() and 1 <= int(raw) <= maximum:
            return int(raw)
        print(f"Please enter a number from 1 to {maximum}.")


def _yes_no(prompt: str, *, default: bool = True) -> bool:
    suffix = "Y/n" if default else "y/N"
    while True:
        raw = input(f"{prompt} [{suffix}]: ").strip().lower()
        if not raw:
            return default
        if raw in {"y", "yes"}:
            return True
        if raw in {"n", "no"}:
            return False
        print("Please enter y or n.")


def _custom_repo_id(role: str) -> tuple[str, str | None]:
    while True:
        repo_id = input(f"  Custom Hugging Face repo for {role} (owner/name): ").strip()
        if re.fullmatch(r"[^/\s]+/[^/\s]+", repo_id):
            break
        print("  Use the form owner/model-name.")

    dimension = None
    if role == "embedding":
        while True:
            dimension = input("  Embedding output dimension: ").strip()
            if dimension.isdigit() and int(dimension) > 0:
                break
            print("  Dimension must be a positive integer.")
    return repo_id, dimension


def _select_model(role: str) -> tuple[str, str | None]:
    choices = LOCAL_MODEL_CHOICES[role]
    print(f"\n  Choose {role} model:")
    for index, (repo_id, label, _dimension) in enumerate(choices, start=1):
        print(f"    [{index}] {repo_id} — {label}")
    print(f"    [{len(choices) + 1}] Enter another compatible Hugging Face repo")
    selected = _choice("  Selection", len(choices) + 1)
    if selected == len(choices) + 1:
        return _custom_repo_id(role)
    repo_id, _label, dimension = choices[selected - 1]
    return repo_id, dimension


def _write_env(updates: dict[str, str]) -> None:
    """Persist selected providers/models without rewriting unrelated settings."""
    text = ENV_FILE.read_text(encoding="utf-8") if ENV_FILE.exists() else ""
    for key, value in updates.items():
        line = f"{key}={value}"
        pattern = re.compile(rf"(?m)^{re.escape(key)}=.*$")
        if pattern.search(text):
            text = pattern.sub(lambda _match, replacement=line: replacement, text)
        else:
            if text and not text.endswith("\n"):
                text += "\n"
            text += f"{line}\n"
        os.environ[key] = value
    ENV_FILE.write_text(text, encoding="utf-8", newline="\n")


def _interactive_selection() -> set[str] | None:
    """Choose a Community local-model bundle and persist it to ``.env``.

    ``None`` means use the providers already configured in ``.env``. An empty
    set means the user cancelled without changing configuration.
    """
    print("\nCommunity model profile:")
    print("  [1] Recommended local bundle (all local capabilities)")
    print("  [2] Custom / hybrid (choose each local capability)")
    print("  [3] Use the local providers already configured in .env")
    print("  [4] Cancel; download nothing")
    profile = _choice("Selection", 4)

    if profile == 4:
        return set()
    if profile == 3:
        return None
    if profile == 1:
        _write_env(RECOMMENDED_LOCAL_CONFIG)
        print(f"\nSaved recommended local providers to {ENV_FILE}.")
        return {"embedding", "reranker", "whisper", "diarization", "docling"}

    updates: dict[str, str] = {}
    selected_roles: set[str] = set()
    prompts = {
        "embedding": "Use a local embedding model for RAG?",
        "reranker": "Use a local reranker for RAG?",
        "whisper": "Use local WhisperX transcription?",
        "diarization": "Use local speaker diarization (also available with remote ASR)?",
    }
    for role, prompt in prompts.items():
        if not _yes_no(prompt, default=role in {"embedding", "reranker"}):
            continue
        model_id, dimension = _select_model(role)
        model_key, provider_key, provider_value = ROLE_ENV_KEYS[role]
        updates[model_key] = model_id
        if role == "diarization" and "whisper" not in selected_roles:
            provider_value = "pyannote"
        updates[provider_key] = provider_value
        if dimension is not None:
            updates["EMBEDDING_DIM"] = dimension
        selected_roles.add(role)

    if _yes_no("Use Docling as the primary local document parser?"):
        updates["PARSER_PROVIDER"] = "docling"
        selected_roles.add("docling")

    if updates:
        _write_env(updates)
        print(f"\nSaved selected local providers to {ENV_FILE}.")
    return selected_roles


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download local models for Interview Copilot.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Models are configured in .env (start from .env.community.example). The script reads the
provider variables you've set and downloads only models assigned to local
providers. Remote-provider roles are skipped because their model data stays
with the provider.

Examples:
  python scripts/init_models.py                  # Interactive Community model setup
  python scripts/init_models.py --only embedding # Embedding only
  python scripts/init_models.py --dry-run        # Show plan without downloading
  python scripts/init_models.py --non-interactive # Use current .env without prompts
""",
    )
    parser.add_argument(
        "--hf-endpoint",
        default=os.getenv("HF_ENDPOINT", DEFAULT_HF_ENDPOINT),
        help=f"HuggingFace endpoint (default: {DEFAULT_HF_ENDPOINT})",
    )
    parser.add_argument(
        "--only",
        choices=("all", "embedding", "reranker", "whisper", "diarization", "docling"),
        default=None,
        help="Download only a specific model type",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be downloaded without actually downloading",
    )
    parser.add_argument(
        "--force-all",
        action="store_true",
        help="Download every configured model, including roles currently using "
        "remote providers.",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Use current .env provider/model settings without prompting",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Show the Community model selection wizard even when stdin is piped",
    )
    args = parser.parse_args()

    if args.interactive and args.non_interactive:
        parser.error("--interactive and --non-interactive are mutually exclusive")

    should_prompt = args.interactive or (
        sys.stdin.isatty()
        and not args.non_interactive
        and args.only is None
        and not args.dry_run
        and not args.force_all
    )

    selected_roles: set[str] | None = None
    if should_prompt:
        selected_roles = _interactive_selection()
        if selected_roles == set():
            print("No model download selected.")
            return 0

    models = {
        "embedding": os.getenv(
            "EMBEDDING_MODEL", MODEL_DEFAULTS["EMBEDDING_MODEL"]
        ).strip(),
        "reranker": os.getenv(
            "RERANKER_MODEL", MODEL_DEFAULTS["RERANKER_MODEL"]
        ).strip(),
        "whisper": os.getenv(
            "TRANSCRIPTION_MODEL", MODEL_DEFAULTS["TRANSCRIPTION_MODEL"]
        ).strip(),
        "diarization": os.getenv(
            "DIARIZATION_MODEL_ID", MODEL_DEFAULTS["DIARIZATION_MODEL_ID"]
        ),
    }

    # Print configuration summary
    print("=" * 60)
    print("Interview Copilot — Local Model Setup")
    print("=" * 60)
    print(f"  HF Endpoint:  {args.hf_endpoint}")
    print(f"  Model Dir:    {MODEL_DIR}")
    print()

    # Make sure the size lookup below (HfApi calls) also goes through the
    # mirror — otherwise dry-run hangs / fails on networks that block
    # huggingface.co. prepare_runtime() sets this too, but only runs later
    # for the actual download path.
    os.environ["HF_ENDPOINT"] = args.hf_endpoint

    tasks = []
    skipped_roles: list[tuple[str, str]] = []
    for role in ("embedding", "reranker", "whisper", "diarization"):
        if selected_roles is not None:
            if role not in selected_roles:
                continue
        elif (args.only or "all") not in ("all", role):
            continue
        repo_id = models[role]
        # Provider gate: remote roles need no local model download.
        needs_local, provider_id, reason = _provider_status(role)
        if not needs_local and not args.force_all:
            print(f"  {role:>13}: {repo_id}")
            print(f"                [skip] {reason}")
            skipped_roles.append((role, provider_id))
            continue
        already = is_already_downloaded(repo_id)
        size = get_remote_size(repo_id)
        status = (
            "[ok]   already downloaded" if already else f"[get]  will download ({size})"
        )
        print(f"  {role:>13}: {repo_id}")
        print(f"                {status}    [{reason}]")
        if not already:
            tasks.append((role, repo_id))

    needs_docling = False
    include_docling = (
        "docling" in selected_roles
        if selected_roles is not None
        else (args.only or "all") in ("all", "docling")
    )
    if include_docling:
        try:
            import docling  # noqa: F401
        except ImportError:
            print(f"  {'docling':>13}: default parsing artifacts")
            print("                [skip] local dependency is not installed")
        else:
            already = is_docling_downloaded()
            status = (
                "[ok]   already downloaded"
                if already
                else "[get]  will download default parsing artifacts"
            )
            print(f"  {'docling':>13}: layout, tables, OCR and enrichment")
            print(f"                {status}    [local parser/fallback]")
            needs_docling = not already

    print()
    if skipped_roles:
        print(
            f"Skipped {len(skipped_roles)} role(s) running through remote APIs. "
            "Run with --force-all to download anyway."
        )
        print()

    if not tasks and not needs_docling:
        print("All models are already downloaded. Nothing to do.")
        return 0

    if args.dry_run:
        print(
            f"Dry run: {len(tasks) + int(needs_docling)} model bundle(s) "
            "would be downloaded."
        )
        return 0

    prepare_runtime(args.hf_endpoint)

    failures = 0
    for role, repo_id in tasks:
        print(f"[{role}] Downloading {repo_id} ...")
        try:
            target = download_snapshot(repo_id)
            print(f"[{role}] [done] Ready: {target}")
        except Exception as exc:
            failures += 1
            print(f"[{role}] [fail] {exc}", file=sys.stderr)
            print(
                f"[{role}]   Try running with --hf-endpoint https://huggingface.co",
                file=sys.stderr,
            )

    if needs_docling:
        print("[docling] Downloading default parsing artifacts ...")
        try:
            target = download_docling_models()
            print(f"[docling] [done] Ready: {target}")
        except Exception as exc:
            failures += 1
            print(f"[docling] [fail] {exc}", file=sys.stderr)

    print()
    if failures:
        print(f"{failures} model download(s) failed.", file=sys.stderr)
        return 1
    print(
        "Done. Start the API server with: cd backend && uvicorn app.main:app --reload --port 8080"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
