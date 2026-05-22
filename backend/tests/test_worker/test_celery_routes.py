"""Phase G regression — celery task routing + per-queue model load.

Locks the two guarantees the worker-split depends on:

  1. ``task_routes`` directs each task to the right queue. If someone
     adds a new task without registering it, this test fails so they
     remember to decide its queue explicitly (or land it on default).
  2. ``_worker_subscribes_to`` correctly detects the queue from CLI /
     env signals. If it always returns False, the light worker would
     load Whisper for nothing; if it always returns True, the dreaming
     worker would crash on missing GPU memory.
"""
from __future__ import annotations

import os
import sys

import pytest


# ── Routing ────────────────────────────────────────────────────────────


def test_heavy_task_routes_to_transcription_queue():
    from app.worker.celery_app import celery_app
    routes = celery_app.conf.task_routes
    assert routes["tasks.process_interview_analysis"]["queue"] == "transcription"


def test_light_tasks_route_to_default_queue():
    from app.worker.celery_app import celery_app
    routes = celery_app.conf.task_routes
    light = [
        "tasks.process_document_ingestion",
        "tasks.dream_for_record",
        "tasks.dream_for_user",
        "tasks.scan_and_dream_batch",
    ]
    for name in light:
        assert routes[name]["queue"] == "default", (
            f"{name} should land on default queue, got {routes[name]}"
        )


def test_every_registered_task_has_a_route():
    """If a new task is defined without a route, the default queue
    silently catches it — fine, but the test exists so the omission
    is visible at PR time and the author can confirm 'yes, default
    is right for this' rather than leaving it accidental."""
    from app.worker.celery_app import celery_app
    routes = celery_app.conf.task_routes
    registered = {
        name for name in celery_app.tasks
        if name.startswith("tasks.")
    }
    unrouted = registered - set(routes.keys())
    assert not unrouted, (
        f"Tasks defined without explicit route: {sorted(unrouted)}. "
        "Add them to celery_app.conf.task_routes."
    )


# ── Queue detection (Whisper-load gate) ────────────────────────────────


def test_worker_subscribes_to_via_env(monkeypatch):
    from app.worker import celery_app as mod

    monkeypatch.setenv("CELERY_QUEUES", "transcription")
    monkeypatch.setattr(sys, "argv", ["celery", "worker"])
    assert mod._worker_subscribes_to("transcription") is True
    assert mod._worker_subscribes_to("default") is False


def test_worker_subscribes_to_via_argv_long(monkeypatch):
    from app.worker import celery_app as mod

    monkeypatch.delenv("CELERY_QUEUES", raising=False)
    monkeypatch.setattr(
        sys, "argv",
        ["celery", "worker", "--queues", "default"],
    )
    assert mod._worker_subscribes_to("default") is True
    assert mod._worker_subscribes_to("transcription") is False


def test_worker_subscribes_to_via_argv_equals(monkeypatch):
    from app.worker import celery_app as mod

    monkeypatch.delenv("CELERY_QUEUES", raising=False)
    monkeypatch.setattr(
        sys, "argv",
        ["celery", "worker", "--queues=transcription,default"],
    )
    assert mod._worker_subscribes_to("transcription") is True
    assert mod._worker_subscribes_to("default") is True
    assert mod._worker_subscribes_to("nonexistent") is False


def test_worker_subscribes_to_via_argv_short_q(monkeypatch):
    from app.worker import celery_app as mod

    monkeypatch.delenv("CELERY_QUEUES", raising=False)
    monkeypatch.setattr(
        sys, "argv",
        ["celery", "worker", "-Q", "transcription"],
    )
    assert mod._worker_subscribes_to("transcription") is True


def test_worker_subscribes_to_returns_false_when_no_queue_signal(monkeypatch):
    """No env, no CLI flag → returns False for everything. The init
    hook then takes the 'light worker' branch (no Whisper). Correct
    fail-safe: if an operator forgets to pass --queues, we'd rather
    skip the expensive model load than try to load it on a process
    that has no business doing transcription."""
    from app.worker import celery_app as mod

    monkeypatch.delenv("CELERY_QUEUES", raising=False)
    monkeypatch.setattr(sys, "argv", ["celery", "worker"])
    assert mod._worker_subscribes_to("transcription") is False
    assert mod._worker_subscribes_to("default") is False
