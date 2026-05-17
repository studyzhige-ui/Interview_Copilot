"""Download local models for Interview Copilot.

Reads model IDs from environment variables (or .env file) and downloads them
from HuggingFace. Supports selective downloading via --only flag.

Usage:
    python scripts/init_models.py              # Download all models
    python scripts/init_models.py --only embedding  # Download embedding model only
    python scripts/init_models.py --dry-run    # Show what would be downloaded

Models are stored under data/cache/models/ and data/cache/huggingface/.
The application auto-detects local snapshots at startup — no path changes needed.
"""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from huggingface_hub import snapshot_download


ROOT_DIR = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT_DIR / "data" / "cache" / "models"
HF_CACHE_DIR = ROOT_DIR / "data" / "cache" / "huggingface"
TORCH_CACHE_DIR = ROOT_DIR / "data" / "cache" / "torch"
DEFAULT_HF_ENDPOINT = "https://hf-mirror.com"

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

# ── Model defaults (must match .env.example) ────────────────────────────

# Env-var → default model name. New shape: each role reads from a single
# *_MODEL env (matches backend/app/core/config.py). The legacy *_MODEL_ID
# names are kept as aliases so old .env files keep working during transition.
MODEL_DEFAULTS = {
    "EMBEDDING_MODEL": "BAAI/bge-m3",
    "RERANKER_MODEL": "BAAI/bge-reranker-v2-m3",
    "TRANSCRIPTION_MODEL": "Systran/faster-whisper-large-v3",
    "DIARIZATION_MODEL_ID": "pyannote-community/speaker-diarization-community-1",
}


def _read_model_env(primary: str, legacy: str, fallback: str) -> str:
    """Read a model env var, preferring the new name + falling back to the legacy one."""
    return (os.getenv(primary) or os.getenv(legacy) or fallback).strip()

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
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    HF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    TORCH_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Clear dead local proxies that block HuggingFace downloads
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "GIT_HTTP_PROXY", "GIT_HTTPS_PROXY"):
        value = os.getenv(key, "")
        if "127.0.0.1:9" in value or "localhost:9" in value:
            os.environ.pop(key, None)

    os.environ["HF_HOME"] = str(HF_CACHE_DIR)
    os.environ["HUGGINGFACE_HUB_CACHE"] = str(HF_CACHE_DIR)
    os.environ["TORCH_HOME"] = str(TORCH_CACHE_DIR)
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
    reason = f"provider {pid!r} → " + ("download local copy" if local else "remote, skip")
    return local, pid, reason


def main() -> None:
    load_dotenv(ROOT_DIR / ".env")

    parser = argparse.ArgumentParser(
        description="Download local models for Interview Copilot.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Models are configured in .env (or .env.example). The script reads the
*PROFILE_ID variables you've set and downloads ONLY the models that
correspond to a ``local-*`` profile — lite-mode profiles (siliconflow-* /
openai-* / etc.) are skipped automatically since the data lives at the
provider, not on your disk.

Examples:
  python scripts/init_models.py                  # Download all locally-configured models
  python scripts/init_models.py --only embedding # Embedding only
  python scripts/init_models.py --dry-run        # Show plan without downloading
  python scripts/init_models.py --force-all      # Ignore PROFILE_ID guards (legacy behaviour)
""",
    )
    parser.add_argument(
        "--hf-endpoint",
        default=os.getenv("HF_ENDPOINT", DEFAULT_HF_ENDPOINT),
        help=f"HuggingFace endpoint (default: {DEFAULT_HF_ENDPOINT})",
    )
    parser.add_argument(
        "--only",
        choices=("all", "embedding", "reranker", "whisper", "diarization"),
        default="all",
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
        help="Bypass PROFILE_ID guards and download every model anyway "
             "(useful when pre-warming a machine that might switch to full mode later).",
    )
    args = parser.parse_args()

    # Read model IDs from environment. New names are *_MODEL (no _ID suffix);
    # the legacy *_MODEL_ID names are honoured as fallbacks so a stale .env
    # still downloads the right thing.
    models = {
        "embedding":   _read_model_env("EMBEDDING_MODEL",      "EMBEDDING_MODEL_ID",      MODEL_DEFAULTS["EMBEDDING_MODEL"]),
        "reranker":    _read_model_env("RERANKER_MODEL",       "RERANKER_MODEL_ID",       MODEL_DEFAULTS["RERANKER_MODEL"]),
        "whisper":     _read_model_env("TRANSCRIPTION_MODEL",  "WHISPER_MODEL_ID",        MODEL_DEFAULTS["TRANSCRIPTION_MODEL"]),
        "diarization": os.getenv("DIARIZATION_MODEL_ID", MODEL_DEFAULTS["DIARIZATION_MODEL_ID"]),
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
        if args.only not in ("all", role):
            continue
        repo_id = models[role]
        # Profile gate — skip lite-mode roles unless --force-all.
        needs_local, provider_id, reason = _provider_status(role)
        if not needs_local and not args.force_all:
            print(f"  {role:>13}: {repo_id}")
            print(f"                [skip] {reason}")
            skipped_roles.append((role, provider_id))
            continue
        already = is_already_downloaded(repo_id)
        size = get_remote_size(repo_id)
        status = "[ok]   already downloaded" if already else f"[get]  will download ({size})"
        print(f"  {role:>13}: {repo_id}")
        print(f"                {status}    [{reason}]")
        if not already:
            tasks.append((role, repo_id))

    print()
    if skipped_roles:
        print(
            f"Skipped {len(skipped_roles)} role(s) running through remote APIs. "
            "Run with --force-all to download anyway."
        )
        print()

    if not tasks:
        print("All models are already downloaded. Nothing to do.")
        return

    if args.dry_run:
        print(f"Dry run: {len(tasks)} model(s) would be downloaded.")
        return

    prepare_runtime(args.hf_endpoint)

    for role, repo_id in tasks:
        print(f"[{role}] Downloading {repo_id} ...")
        try:
            target = download_snapshot(repo_id)
            print(f"[{role}] [done] Ready: {target}")
        except Exception as exc:
            print(f"[{role}] [fail] {exc}", file=sys.stderr)
            print(f"[{role}]   Try running with --hf-endpoint https://huggingface.co", file=sys.stderr)

    print()
    print("Done. Start the API server with: cd backend && uvicorn app.main:app --reload --port 8080")


if __name__ == "__main__":
    main()
