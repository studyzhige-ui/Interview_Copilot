"""Owned, bounded on-disk input for an evidence-producing operation.

A hash taken *after* transcription cannot identify bytes read earlier. Capture
one immutable copy before model work instead. The worker owns this context, not
its cancellable async waiter, so a cancelled HTTP request cannot delete audio
while an already-running model still reads it. This is not an OS sandbox.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import stat
from tempfile import TemporaryDirectory
from typing import Iterator


_SHA256_VERSION = re.compile(r"sha256:([0-9a-f]{64})\Z")
_COPY_BLOCK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class EvidenceSource:
    path: str
    file_asset_id: str
    file_asset_version: str
    sha256: str
    size_bytes: int


def _identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


@contextmanager
def capture_evidence_source(
    path: str,
    *,
    file_asset_id: str,
    file_asset_version: str,
    max_bytes: int,
) -> Iterator[EvidenceSource]:
    """Snapshot an authorized local regular file and reject a changed source.

    The caller remains responsible for account/asset authorization. An explicit
    sha256 version must match the actual bytes; legacy asset-only versions stay
    explicitly unverified rather than pretending to supply a checksum.
    """
    if (
        not isinstance(file_asset_id, str)
        or not file_asset_id.strip()
        or not isinstance(file_asset_version, str)
        or not file_asset_version.strip()
        or type(max_bytes) is not int
        or max_bytes <= 0
    ):
        raise ValueError("invalid_evidence_source_identity_or_limit")
    expected = _SHA256_VERSION.fullmatch(file_asset_version)
    if file_asset_version.startswith("sha256:") and expected is None:
        raise ValueError("invalid_evidence_source_version")

    original = Path(path).absolute()
    before = original.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("evidence_source_requires_regular_file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(original, flags)
    try:
        opened = os.fstat(fd)
        identity = _identity(opened)
        if identity != _identity(before):
            raise ValueError("audio_source_changed")
        if not stat.S_ISREG(opened.st_mode) or not 0 < opened.st_size <= max_bytes:
            raise ValueError("audio_input_size_invalid")

        def check_original() -> None:
            try:
                current = original.lstat()
            except OSError as exc:
                raise ValueError("audio_source_changed") from exc
            if _identity(os.fstat(fd)) != identity or _identity(current) != identity:
                raise ValueError("audio_source_changed")

        with TemporaryDirectory(prefix="interview-evidence-") as directory:
            # No user-controlled basename or parent directory reaches the worker.
            captured = Path(directory) / "source.audio"
            digest = hashlib.sha256()
            copied = 0
            with captured.open("xb") as output:
                while block := os.read(fd, _COPY_BLOCK_BYTES):
                    copied += len(block)
                    if copied > max_bytes:
                        raise ValueError("audio_input_size_invalid")
                    output.write(block)
                    digest.update(block)
            check_original()
            if copied != opened.st_size:
                raise ValueError("audio_source_changed")
            checksum = digest.hexdigest()
            if expected is not None and checksum != expected.group(1):
                raise ValueError("audio_source_checksum_mismatch")
            captured.chmod(0o400)
            captured_identity = _identity(captured.stat())
            yield EvidenceSource(
                path=str(captured),
                file_asset_id=file_asset_id,
                file_asset_version=file_asset_version,
                sha256=checksum,
                size_bytes=copied,
            )
            check_original()
            if _identity(captured.stat()) != captured_identity:
                raise ValueError("audio_snapshot_changed")
    finally:
        os.close(fd)
