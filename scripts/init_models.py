import argparse
import os
from pathlib import Path

from dotenv import load_dotenv
from huggingface_hub import hf_hub_download, snapshot_download


ROOT_DIR = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT_DIR / "backend" / "data" / "models"
HF_CACHE_DIR = ROOT_DIR / "backend" / "data" / "hf_cache"
TORCH_CACHE_DIR = ROOT_DIR / "backend" / "data" / "torch_cache"
DEFAULT_HF_ENDPOINT = "https://hf-mirror.com"

FASTER_WHISPER_FILES = (
    ".gitattributes",
    "README.md",
    "config.json",
    "model.bin",
    "tokenizer.json",
    "vocabulary.txt",
)


def repo_dir(repo_id: str) -> Path:
    return MODEL_DIR / repo_id.replace("/", "--")


def prepare_runtime(hf_endpoint: str) -> None:
    load_dotenv()
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    HF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    TORCH_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "GIT_HTTP_PROXY", "GIT_HTTPS_PROXY"):
        value = os.getenv(key, "")
        if "127.0.0.1:9" in value or "localhost:9" in value:
            os.environ.pop(key, None)

    os.environ["HF_HOME"] = str(HF_CACHE_DIR)
    os.environ["HUGGINGFACE_HUB_CACHE"] = str(HF_CACHE_DIR)
    os.environ["TORCH_HOME"] = str(TORCH_CACHE_DIR)
    os.environ["HF_ENDPOINT"] = hf_endpoint


def download_snapshot(repo_id: str, max_workers: int = 1) -> Path:
    target_dir = repo_dir(repo_id)
    path = snapshot_download(
        repo_id=repo_id,
        local_dir=str(target_dir),
        max_workers=max_workers,
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


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Initialize local model files for Interview Copilot.")
    parser.add_argument("--hf-endpoint", default=os.getenv("HF_ENDPOINT", DEFAULT_HF_ENDPOINT))
    parser.add_argument("--embedding-model", default=os.getenv("EMBEDDING_MODEL_ID", "BAAI/bge-small-zh-v1.5"))
    parser.add_argument("--reranker-model", default=os.getenv("RERANKER_MODEL_ID", "BAAI/bge-reranker-base"))
    parser.add_argument("--whisper-model", default=os.getenv("WHISPER_MODEL_ID", "Systran/faster-whisper-large-v2"))
    parser.add_argument(
        "--diarization-model",
        default=os.getenv("DIARIZATION_MODEL_ID", "pyannote-community/speaker-diarization-community-1"),
    )
    parser.add_argument(
        "--only",
        choices=("all", "embedding", "reranker", "whisper", "diarization"),
        default="all",
    )
    args = parser.parse_args()

    prepare_runtime(args.hf_endpoint)

    tasks = []
    if args.only in ("all", "embedding"):
        tasks.append(("embedding", args.embedding_model, lambda: download_snapshot(args.embedding_model)))
    if args.only in ("all", "reranker"):
        tasks.append(("reranker", args.reranker_model, lambda: download_snapshot(args.reranker_model)))
    if args.only in ("all", "whisper"):
        tasks.append(("whisper", args.whisper_model, lambda: download_faster_whisper(args.whisper_model)))
    if args.only in ("all", "diarization"):
        tasks.append(("diarization", args.diarization_model, lambda: download_snapshot(args.diarization_model)))

    for label, repo_id, runner in tasks:
        print(f"[init_models] downloading {label}: {repo_id}")
        target = runner()
        print(f"[init_models] ready: {target}")

    print("[init_models] completed")


if __name__ == "__main__":
    main()
