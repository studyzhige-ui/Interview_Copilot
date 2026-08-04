"""Managed runtime files that belong under ``APP_DATA_DIR``."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from threading import Lock
from typing import Any

from app.core.config import settings

_JSONL_LOCK = Lock()
_JSONL_MAX_BYTES = 50 * 1024 * 1024


def runtime_temp_dir() -> Path:
    """Return the one directory used for temporary application downloads."""
    path = Path(settings.APP_DATA_DIR) / "tmp"
    path.mkdir(parents=True, exist_ok=True)
    return path


def create_runtime_temp_file(*, suffix: str = "") -> str:
    """Create a closed temporary file in ``data/tmp`` for path-based APIs."""
    fd, path = tempfile.mkstemp(suffix=suffix, dir=runtime_temp_dir())
    os.close(fd)
    return path


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    """Append one JSON object and cap the file at two 50 MiB generations."""
    line = json.dumps(payload, ensure_ascii=False) + "\n"
    encoded_size = len(line.encode("utf-8"))
    path.parent.mkdir(parents=True, exist_ok=True)
    with _JSONL_LOCK:
        if path.exists() and path.stat().st_size + encoded_size > _JSONL_MAX_BYTES:
            backup = path.with_name(f"{path.name}.1")
            backup.unlink(missing_ok=True)
            path.replace(backup)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(line)


def remove_session_results(session_id: str) -> None:
    """Remove oversized tool-result files after their conversation is deleted."""
    base = (Path(settings.APP_DATA_DIR) / "agent-results").resolve()
    target = (base / session_id).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        return
    if target != base:
        shutil.rmtree(target, ignore_errors=True)


__all__ = [
    "append_jsonl",
    "create_runtime_temp_file",
    "remove_session_results",
    "runtime_temp_dir",
]
