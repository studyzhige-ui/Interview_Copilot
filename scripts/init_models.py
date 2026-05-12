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
from huggingface_hub import hf_hub_download, snapshot_download


ROOT_DIR = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT_DIR / "data" / "cache" / "models"
HF_CACHE_DIR = ROOT_DIR / "data" / "cache" / "huggingface"
TORCH_CACHE_DIR = ROOT_DIR / "data" / "cache" / "torch"
DEFAULT_HF_ENDPOINT = "https://hf-mirror.com"

# faster-whisper uses CTranslate2 format — only these files are needed
FASTER_WHISPER_FILES = (
    "config.json",
    "model.bin",
    "tokenizer.json",
    "vocabulary.txt",
)

# ── Model defaults (must match .env.example) ────────────────────────────

MODEL_DEFAULTS = {
    "EMBEDDING_MODEL_ID": "BAAI/bge-m3",
    "RERANKER_MODEL_ID": "BAAI/bge-reranker-base",
    "WHISPER_MODEL_ID": "Systran/faster-whisper-large-v2",
    "DIARIZATION_MODEL_ID": "pyannote-community/speaker-diarization-community-1",
}

# ── Size estimates for user display ──────────────────────────────────────

SIZE_ESTIMATES = {
    "embedding": {
        "BAAI/bge-m3": "~1.06 GB",
        "BAAI/bge-large-zh-v1.5": "~620 MB",
        "BAAI/bge-small-en-v1.5": "~64 MB",
        "sentence-transformers/all-MiniLM-L6-v2": "~86 MB",
        "intfloat/multilingual-e5-large": "~1.06 GB",
    },
    "reranker": {
        "BAAI/bge-reranker-base": "~530 MB",
        "BAAI/bge-reranker-large": "~1.06 GB",
        "BAAI/bge-reranker-v2-m3": "~1.08 GB",
    },
    "whisper": {
        "Systran/faster-whisper-large-v2": "~3.09 GB",
        "Systran/faster-whisper-medium": "~1.5 GB",
        "Systran/faster-whisper-small": "~486 MB",
        "Systran/faster-whisper-base": "~148 MB",
    },
    "diarization": {
        "pyannote-community/speaker-diarization-community-1": "~17 MB",
        "pyannote/speaker-diarization-3.1": "~17 MB",
    },
}


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


def download_faster_whisper(repo_id: str) -> Path:
    target_dir = repo_dir(repo_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    for filename in FASTER_WHISPER_FILES:
        hf_hub_download(
            repo_id=repo_id,
            filename=filename,
            local_dir=str(target_dir),
        )
    return target_dir


def is_already_downloaded(repo_id: str) -> bool:
    """Check if a model appears to be already downloaded."""
    target = repo_dir(repo_id)
    if target.exists() and any(target.iterdir()):
        return True
    # Also check HF cache
    snapshot_root = HF_CACHE_DIR / f"models--{repo_id.replace('/', '--')}" / "snapshots"
    if snapshot_root.exists() and any(snapshot_root.iterdir()):
        return True
    return False


def get_size_estimate(role: str, repo_id: str) -> str:
    return SIZE_ESTIMATES.get(role, {}).get(repo_id, "unknown size")


def main() -> None:
    load_dotenv(ROOT_DIR / ".env")

    parser = argparse.ArgumentParser(
        description="Download local models for Interview Copilot.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Models are configured in .env (or .env.example). Change the model IDs there
before running this script to download different model variants.

Examples:
  python scripts/init_models.py                  # Download all models
  python scripts/init_models.py --only embedding # Download embedding model only
  python scripts/init_models.py --dry-run        # Show what would be downloaded
  python scripts/init_models.py --hf-endpoint https://huggingface.co  # Use official HF
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
    args = parser.parse_args()

    # Read model IDs from environment
    models = {
        "embedding": os.getenv("EMBEDDING_MODEL_ID", MODEL_DEFAULTS["EMBEDDING_MODEL_ID"]),
        "reranker": os.getenv("RERANKER_MODEL_ID", MODEL_DEFAULTS["RERANKER_MODEL_ID"]),
        "whisper": os.getenv("WHISPER_MODEL_ID", MODEL_DEFAULTS["WHISPER_MODEL_ID"]),
        "diarization": os.getenv("DIARIZATION_MODEL_ID", MODEL_DEFAULTS["DIARIZATION_MODEL_ID"]),
    }

    # Print configuration summary
    print("=" * 60)
    print("Interview Copilot — Local Model Setup")
    print("=" * 60)
    print(f"  HF Endpoint:  {args.hf_endpoint}")
    print(f"  Model Dir:    {MODEL_DIR}")
    print()

    tasks = []
    for role in ("embedding", "reranker", "whisper", "diarization"):
        if args.only not in ("all", role):
            continue
        repo_id = models[role]
        already = is_already_downloaded(repo_id)
        size = get_size_estimate(role, repo_id)
        status = "✓ already downloaded" if already else f"⬇ will download ({size})"
        print(f"  {role:>13}: {repo_id}")
        print(f"                {status}")
        if not already:
            is_whisper = role == "whisper"
            downloader = download_faster_whisper if is_whisper else download_snapshot
            tasks.append((role, repo_id, downloader))

    print()

    if not tasks:
        print("All models are already downloaded. Nothing to do.")
        return

    if args.dry_run:
        print(f"Dry run: {len(tasks)} model(s) would be downloaded.")
        return

    prepare_runtime(args.hf_endpoint)

    for role, repo_id, downloader in tasks:
        print(f"[{role}] Downloading {repo_id} ...")
        try:
            target = downloader(repo_id)
            print(f"[{role}] ✓ Ready: {target}")
        except Exception as exc:
            print(f"[{role}] ✗ Failed: {exc}", file=sys.stderr)
            print(f"[{role}]   Try running with --hf-endpoint https://huggingface.co", file=sys.stderr)

    print()
    print("Done. Start the API server with: cd backend && uvicorn app.main:app --reload --port 8080")


if __name__ == "__main__":
    main()
