"""Regression for CI #143: /proc can disappear between open() and read()."""

from pathlib import Path

import pytest

from tests.process_assertions import process_stopped


def test_process_exit_during_status_read_is_not_a_cleanup_failure(monkeypatch):
    for error in (FileNotFoundError, ProcessLookupError):

        def vanished(self, failure=error):
            raise failure()

        monkeypatch.setattr(Path, "read_text", vanished)
        assert process_stopped(1234)


def test_live_zombie_and_unreadable_process_are_distinct(monkeypatch):
    for state, expected in (("R", False), ("S", False), ("D", False), ("Z", True)):
        monkeypatch.setattr(
            Path,
            "read_text",
            lambda self, s=state: f"Name:\ttest\nState:\t{s} (state)\n",
        )
        assert process_stopped(1234) is expected

    def unreadable(self):
        raise PermissionError("synthetic denied /proc read")

    monkeypatch.setattr(Path, "read_text", unreadable)
    with pytest.raises(PermissionError):
        process_stopped(1234)
