"""Real file lifecycle and cancellation; no model or network dependencies."""

import asyncio
import hashlib
import os
from pathlib import Path
import threading

import pytest

from app.core.bounded_work import BoundedWorkPool
from app.media.application.evidence_source import capture_evidence_source


def capture(path, *, version="file_asset:fa_test", maximum=2_000_000):
    return capture_evidence_source(
        str(path),
        file_asset_id="fa_test",
        file_asset_version=version,
        max_bytes=maximum,
    )


def test_snapshot_binds_actual_bytes_and_cleans_up(tmp_path):
    original = tmp_path / "recording.wav"
    original.write_bytes(b"owned-audio")
    checksum = hashlib.sha256(original.read_bytes()).hexdigest()
    with capture(original, version=f"sha256:{checksum}") as source:
        snapshot = Path(source.path)
        assert snapshot != original
        assert snapshot.read_bytes() == b"owned-audio"
        assert source.sha256 == checksum and source.size_bytes == 11
        assert source.file_asset_id == "fa_test"
        assert source.file_asset_version == f"sha256:{checksum}"
    assert not snapshot.exists()
    assert original.read_bytes() == b"owned-audio"


@pytest.mark.parametrize("version", ["sha256:" + "0" * 64, "sha256:not-a-digest"])
def test_declared_checksum_is_not_relabelled_after_reading(tmp_path, version):
    original = tmp_path / "recording.wav"
    original.write_bytes(b"actual")
    with pytest.raises(
        ValueError, match="checksum_mismatch|invalid_evidence_source_version"
    ):
        with capture(original, version=version):
            pytest.fail("model work must not start on the wrong source")


def test_source_mutation_rejects_result_but_never_changes_snapshot(tmp_path):
    original = tmp_path / "recording.wav"
    original.write_bytes(b"before")
    with pytest.raises(ValueError, match="audio_source_changed"):
        with capture(original) as source:
            snapshot = Path(source.path)
            original.write_bytes(b"after!")
            assert snapshot.read_bytes() == b"before"
    assert not snapshot.exists()


def test_replacement_with_same_content_still_changes_source_identity(tmp_path):
    original = tmp_path / "recording.wav"
    replacement = tmp_path / "replacement.wav"
    original.write_bytes(b"same")
    replacement.write_bytes(b"same")
    with pytest.raises(ValueError, match="audio_source_changed"):
        with capture(original):
            replacement.replace(original)


@pytest.mark.parametrize("kind", ["directory", "symlink", "empty", "oversize"])
def test_non_regular_or_unbounded_sources_fail_before_work(tmp_path, kind):
    original = tmp_path / "source"
    if kind == "directory":
        original.mkdir()
    elif kind == "symlink":
        target = tmp_path / "target"
        target.write_bytes(b"audio")
        original.symlink_to(target)
    else:
        original.write_bytes(b"" if kind == "empty" else b"x" * 11)
    with pytest.raises(ValueError, match="regular_file|audio_input_size_invalid"):
        with capture(original, maximum=10):
            pytest.fail("invalid source reached model work")


def test_copy_reads_fixed_blocks_not_the_entire_upload(monkeypatch, tmp_path):
    from app.media.application import evidence_source

    original = tmp_path / "source.wav"
    original.write_bytes(b"a" * 2_500_000)
    real_read = os.read
    requested = []

    def read(fd, size):
        requested.append(size)
        return real_read(fd, size)

    monkeypatch.setattr(evidence_source.os, "read", read)
    with capture(original, maximum=3_000_000) as source:
        assert source.size_bytes == 2_500_000
    assert len(requested) >= 3
    assert max(requested) <= 1024 * 1024


async def test_waiter_cancellation_cannot_remove_running_workers_source(tmp_path):
    original = tmp_path / "source.wav"
    original.write_bytes(b"audio")
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    paths = []
    pool = BoundedWorkPool("evidence-source-test", workers=1, queue_size=0)

    def work():
        try:
            with capture(original) as source:
                paths.append(Path(source.path))
                started.set()
                assert release.wait(5), "test must release worker"
                assert paths[0].read_bytes() == b"audio"
        finally:
            finished.set()

    waiter = asyncio.create_task(pool.run(work))
    try:
        assert await asyncio.to_thread(started.wait, 5)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert paths[0].exists()
        assert pool.snapshot()["inflight"] == 1
        release.set()
        assert await asyncio.to_thread(finished.wait, 5)
        assert not paths[0].exists()
    finally:
        release.set()
        pool.shutdown(wait=True)
