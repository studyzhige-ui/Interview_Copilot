"""Backups preserve current filesystem blobs and immutable restore semantics."""

import os
import json
from argparse import Namespace

import pytest

from app.core import storage
from scripts import backup


def test_restore_rejects_wrong_storage_before_touching_database(tmp_path, monkeypatch):
    (tmp_path / "database.dump").write_bytes(b"not-a-real-dump")
    (tmp_path / "objects").mkdir()
    (tmp_path / "manifest.json").write_text(
        json.dumps({"storage_backend": "s3"}), encoding="utf-8"
    )
    monkeypatch.setattr(storage.settings, "STORAGE_BACKEND", "filesystem")
    with pytest.raises(ValueError, match="original storage backend"):
        backup.restore_backup(Namespace(backup=str(tmp_path), restore_objects=True))


@pytest.mark.skipif(
    not hasattr(os, "O_DIRECTORY"), reason="production storage runs on Linux"
)
def test_local_object_backup_restore_and_collision(tmp_path, monkeypatch):
    original = tmp_path / "live"
    (original / "uploads/owner").mkdir(parents=True)
    (original / "uploads/owner/recording.wav").write_bytes(b"exact-original-bytes")
    monkeypatch.setattr(storage.settings, "STORAGE_BACKEND", "filesystem")
    monkeypatch.setattr(storage.settings, "STORAGE_DIR", str(original))
    monkeypatch.setattr(storage, "check_free_space", lambda size=0: None)
    saved = tmp_path / "backup/objects"
    assert backup._backup_objects(saved) == 1
    restored = tmp_path / "restored"
    monkeypatch.setattr(storage.settings, "STORAGE_DIR", str(restored))
    assert backup._restore_objects(saved) == 1
    assert (
        restored / "uploads/owner/recording.wav"
    ).read_bytes() == b"exact-original-bytes"
    with pytest.raises(FileExistsError):
        backup._restore_objects(saved)
    assert (
        restored / "uploads/owner/recording.wav"
    ).read_bytes() == b"exact-original-bytes"


def test_missing_or_recursive_storage_backup_is_not_reported_as_success(
    tmp_path, monkeypatch
):
    root = tmp_path / "live"
    monkeypatch.setattr(storage.settings, "STORAGE_BACKEND", "filesystem")
    monkeypatch.setattr(storage.settings, "STORAGE_DIR", str(root))
    with pytest.raises(FileNotFoundError):
        backup._backup_objects(tmp_path / "backup")
    root.mkdir()
    with pytest.raises(ValueError, match="outside"):
        backup._backup_objects(root / "nested-backup")
