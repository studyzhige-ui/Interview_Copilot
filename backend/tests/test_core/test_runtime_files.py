from __future__ import annotations

import json
from pathlib import Path

from app.core import runtime_files


def test_temp_files_and_session_results_stay_under_data(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_files.settings, "APP_DATA_DIR", str(tmp_path))

    temp_path = Path(runtime_files.create_runtime_temp_file(suffix=".pdf"))
    assert temp_path.parent == tmp_path / "tmp"
    assert temp_path.is_file()

    result = tmp_path / "agent-results" / "session-1" / "call.txt"
    result.parent.mkdir(parents=True)
    result.write_text("result", encoding="utf-8")
    runtime_files.remove_session_results("session-1")
    assert not result.parent.exists()


def test_jsonl_rotates_to_one_bounded_backup(tmp_path, monkeypatch):
    path = tmp_path / "metrics.jsonl"
    monkeypatch.setattr(runtime_files, "_JSONL_MAX_BYTES", 20)

    runtime_files.append_jsonl(path, {"value": "first"})
    runtime_files.append_jsonl(path, {"value": "second"})

    backup = tmp_path / "metrics.jsonl.1"
    assert backup.is_file()
    assert json.loads(path.read_text(encoding="utf-8"))["value"] == "second"
