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
import fnmatch
import hashlib
import json
import tempfile
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[1]
SOURCE_ROOT = (
    ROOT_DIR / "backend" if (ROOT_DIR / "backend" / "app").is_dir() else ROOT_DIR
)
sys.path.insert(0, str(SOURCE_ROOT))
load_dotenv(ROOT_DIR / ".env")

from app.core.config import settings  # noqa: E402
from app.core.model_assets import inspect_directory, inspect_model, validate_model_id  # noqa: E402
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
    "alignment": (
        (
            "jonatasgrosman/wav2vec2-large-xlsr-53-chinese-zh-cn",
            "Chinese forced alignment for auditable interview QA",
            None,
        ),
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
    "TRANSCRIPTION_ALIGNMENT_MODEL": LOCAL_MODEL_CHOICES["alignment"][0][0],
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
    "TRANSCRIPTION_ALIGNMENT_MODEL": settings.TRANSCRIPTION_ALIGNMENT_MODEL,
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
    "alignment": (
        "TRANSCRIPTION_ALIGNMENT_MODEL",
        "TRANSCRIPTION_PROVIDER",
        "local_whisperx",
    ),
    "diarization": ("DIARIZATION_MODEL_ID", "DIARIZATION_MODE", "auto"),
}

# Remote metadata is opt-in during dry runs. Real downloads resolve an exact
# immutable revision once, verify all expected file sizes and record hashes.


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
    # This explicit setup command is the only process allowed to fetch weights.
    # Do this BEFORE importing huggingface_hub (it reads environment at import).
    os.environ["HF_HUB_OFFLINE"] = "0"
    os.environ["TRANSFORMERS_OFFLINE"] = "0"
    os.environ["HF_ENDPOINT"] = hf_endpoint
    # Xet bridge endpoints are frequently unavailable on constrained Windows
    # networks. Plain HTTPS/LFS supports resume and is sufficient here.
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "600")


def download_snapshot(repo_id: str) -> Path:
    validate_model_id(repo_id)
    from huggingface_hub import HfApi, snapshot_download

    requested = settings.MODEL_REVISIONS_JSON.get(repo_id, "main")
    info = HfApi().model_info(repo_id, revision=requested, files_metadata=True)
    revision = info.sha
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("download_revision_unresolved")
    ignored = ("*.msgpack", "tf_model.h5", "*.ot")
    expected = [
        entry
        for entry in info.siblings
        if not any(fnmatch.fnmatch(entry.rfilename, pat) for pat in ignored)
    ]
    if not expected or len(expected) > 4096:
        raise ValueError("download_file_manifest_capacity")
    export_root = repo_dir(repo_id)
    target_dir = export_root / ".revisions" / revision
    path = Path(
        snapshot_download(
            repo_id=repo_id,
            revision=revision,
            local_dir=str(target_dir),
            max_workers=2,
            ignore_patterns=ignored,
        )
    )
    if path.resolve() != target_dir.resolve():
        raise ValueError("download_returned_unexpected_directory")
    files = {}
    for entry in expected:
        relative = Path(entry.rfilename)
        if relative.is_absolute() or ".." in relative.parts or "\\" in str(relative):
            raise ValueError("download_file_outside_model")
        asset = (path / relative).resolve(strict=True)
        if not asset.is_relative_to(path.resolve()) or not asset.is_file():
            raise ValueError("download_file_outside_model")
        if (
            type(entry.size) is not int
            or entry.size < 0
            or asset.stat().st_size != entry.size
        ):
            raise ValueError("download_file_incomplete")
        # Empty repository placeholders are not inference assets.
        if entry.size:
            with asset.open("rb") as handle:
                digest = hashlib.file_digest(handle, "sha256").hexdigest()
            files[entry.rfilename] = {"size": entry.size, "sha256": digest}
    manifest = {
        "schema_version": 1,
        "model_id": repo_id,
        "revision": revision,
        "files": files,
    }
    fd, name = tempfile.mkstemp(prefix=".snapshot-", dir=path)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, sort_keys=True, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path / ".copilot-snapshot.json")
    finally:
        Path(name).unlink(missing_ok=True)
    report = inspect_directory(repo_id, path, revision=revision)
    if not report.loadable_candidate:
        raise ValueError("download_layout_incomplete:" + ",".join(report.issues))
    fd, name = tempfile.mkstemp(prefix=".activate-", dir=export_root)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(revision + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, export_root / ".copilot-active-revision")
    finally:
        Path(name).unlink(missing_ok=True)
    return path


def is_already_downloaded(repo_id: str) -> bool:
    """Reuse the same read-only structure/revision check as runtime loading."""
    result = inspect_model(
        repo_id,
        model_root=MODEL_DIR,
        cache_root=HF_CACHE_DIR,
        revision=settings.MODEL_REVISIONS_JSON.get(repo_id),
    )
    return result.loadable_candidate


def is_docling_downloaded() -> bool:
    # Custom bundles must additionally pass Docling's offline loader check.
    return inspect_directory("docling", DOCLING_MODELS_DIR).loadable_candidate


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
    elif role in ("whisper", "alignment", "diarization"):
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
        return {
            "embedding",
            "reranker",
            "whisper",
            "alignment",
            "diarization",
            "docling",
        }

    updates: dict[str, str] = {}
    selected_roles: set[str] = set()
    prompts = {
        "embedding": "Use a local embedding model for RAG?",
        "reranker": "Use a local reranker for RAG?",
        "whisper": "Use local WhisperX transcription?",
        "alignment": "Download the forced-alignment model for interview QA?",
        "diarization": "Use local speaker diarization (also available with remote ASR)?",
    }
    for role, prompt in prompts.items():
        default = role in {"embedding", "reranker"} or (
            role == "alignment" and "whisper" in selected_roles
        )
        if not _yes_no(prompt, default=default):
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
        choices=(
            "all",
            "embedding",
            "reranker",
            "whisper",
            "alignment",
            "diarization",
            "docling",
        ),
        default=None,
        help="Download only a specific model type",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Read-only local plan: no downloads, remote size requests or directory writes",
    )
    parser.add_argument(
        "--check-remote",
        action="store_true",
        help="Explicitly permit remote size lookup (including with --dry-run)",
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

    if args.interactive and (args.non_interactive or args.dry_run):
        parser.error(
            "--interactive cannot be combined with --non-interactive or --dry-run"
        )

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
        "alignment": os.getenv(
            "TRANSCRIPTION_ALIGNMENT_MODEL",
            MODEL_DEFAULTS["TRANSCRIPTION_ALIGNMENT_MODEL"],
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
    if args.check_remote:
        os.environ["HF_HUB_OFFLINE"] = "0"
        os.environ["TRANSFORMERS_OFFLINE"] = "0"

    tasks = []
    skipped_roles: list[tuple[str, str]] = []
    for role in ("embedding", "reranker", "whisper", "alignment", "diarization"):
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
        size = get_remote_size(repo_id) if args.check_remote else "not queried"
        status = (
            "[local] structural candidate; loader/GPU not tested"
            if already
            else f"[get]  missing or incomplete ({size})"
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
            import importlib.util

            if importlib.util.find_spec("docling") is None:
                raise ImportError("docling")
        except ImportError:
            print(f"  {'docling':>13}: default parsing artifacts")
            print("                [skip] local dependency is not installed")
        else:
            already = is_docling_downloaded()
            status = (
                "[local] bundle present; offline loader not exercised"
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
        print(
            "No selected download tasks. This is not an inference/GPU acceptance result."
        )
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
            print(
                f"[{role}] [downloaded] {target}; offline loader/GPU test still required"
            )
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
            print(
                f"[docling] [downloaded] {target}; offline loader test still required"
            )
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
