"""Celery task routing + per-queue model loading regression tests.

Locks the two guarantees the worker-split depends on:

  1. ``task_routes`` directs each task to the right queue. If someone
     adds a new task without registering it, this test fails so they
     remember to decide its queue explicitly (or land it on default).
  2. ``_worker_subscribes_to`` correctly detects the queue from CLI /
     env signals so only transcription workers load Whisper.
"""

from __future__ import annotations

import sys

# ── Routing ────────────────────────────────────────────────────────────


def test_heavy_task_routes_to_transcription_queue():
    from app.task_queue.celery_app import celery_app

    routes = celery_app.conf.task_routes
    assert routes["tasks.process_interview_analysis"]["queue"] == "transcription"


def test_mock_review_routes_to_background_queue():
    from app.task_queue.celery_app import celery_app

    assert (
        celery_app.conf.task_routes["tasks.process_mock_interview_review"]["queue"]
        == "background"
    )


def test_conversation_turn_routes_to_isolated_queue():
    from app.task_queue.celery_app import celery_app

    assert (
        celery_app.conf.task_routes["tasks.process_conversation_turn"]["queue"]
        == "turns"
    )


def test_pipeline_tasks_route_to_pipeline_queue():
    from app.task_queue.celery_app import celery_app

    routes = celery_app.conf.task_routes
    pipeline = [
        "tasks.process_document_ingestion",
        "tasks.process_resume_parse",
        "tasks.drain_index_outbox_jobs",
    ]
    for name in pipeline:
        assert routes[name]["queue"] == "pipeline", (
            f"{name} should land on pipeline queue, got {routes[name]}"
        )


def test_control_tasks_route_to_default_queue():
    from app.task_queue.celery_app import celery_app

    routes = celery_app.conf.task_routes
    control = [
        "tasks.refresh_model_catalog",
        "tasks.sweep_stale_interview_records",
        "tasks.sweep_stale_pipeline_records",
        "tasks.sweep_orphan_file_assets",
        "tasks.sweep_runtime_files",
        "tasks.sweep_expired_conversation_deletion_receipts",
        "tasks.repair_pending_automation_turns",
        "tasks.schedule_due_persistent_tasks",
        "tasks.consolidate_agent_memory",
        "tasks.drain_cleanup_outbox_jobs",
    ]
    for name in control:
        assert routes[name]["queue"] == "default"


def test_background_tasks_have_their_own_queue():
    from app.task_queue.celery_app import celery_app

    routes = celery_app.conf.task_routes
    for name in ("tasks.process_mock_interview_review",):
        assert routes[name]["queue"] == "background"


def test_outbox_beat_entries_are_reconciliation_fallbacks_not_hot_pollers():
    from app.task_queue.celery_app import celery_app

    schedule = celery_app.conf.beat_schedule
    names = (
        "index-outbox-reconcile-every-five-minutes",
        "cleanup-outbox-reconcile-every-five-minutes",
    )
    for name in names:
        entry = schedule[name]
        assert entry["schedule"].minute == set(range(0, 60, 5))
        assert entry["options"]["expires"] == 240


def test_persistent_task_scheduler_runs_every_minute_with_short_expiry():
    from app.task_queue.celery_app import celery_app

    entry = celery_app.conf.beat_schedule["persistent-task-scheduler"]
    assert entry["task"] == "tasks.schedule_due_persistent_tasks"
    assert entry["schedule"].minute == set(range(60))
    assert entry["options"]["expires"] == 50


def test_conversation_deletion_receipt_retention_runs_daily():
    from app.task_queue.celery_app import celery_app

    entry = celery_app.conf.beat_schedule["conversation-deletion-receipts-sweep-daily"]
    assert entry["task"] == "tasks.sweep_expired_conversation_deletion_receipts"
    assert entry["schedule"].hour == {4}
    assert entry["schedule"].minute == {50}
    assert entry["options"]["expires"] == 3600


def test_community_compose_merges_background_and_default_workers():
    from pathlib import Path

    import yaml

    compose_path = Path(__file__).resolve().parents[3] / "docker-compose.yml"
    services = yaml.safe_load(compose_path.read_text(encoding="utf-8"))["services"]

    assert "worker-background" not in services
    assert "worker-light" not in services
    jobs = services["worker-jobs"]
    assert jobs["environment"]["CELERY_QUEUES"] == "background,default"
    assert "--queues=background,default" in jobs["command"]


def test_every_registered_task_has_a_route():
    """If a new task is defined without a route, the default queue
    silently catches it — fine, but the test exists so the omission
    is visible at PR time and the author can confirm 'yes, default
    is right for this' rather than leaving it accidental."""
    from app.task_queue.celery_app import celery_app

    routes = celery_app.conf.task_routes
    registered = {name for name in celery_app.tasks if name.startswith("tasks.")}
    unrouted = registered - set(routes.keys())
    assert not unrouted, (
        f"Tasks defined without explicit route: {sorted(unrouted)}. "
        "Add them to celery_app.conf.task_routes."
    )


# ── Queue detection (Whisper-load gate) ────────────────────────────────


def test_worker_subscribes_to_via_env(monkeypatch):
    from app.task_queue import celery_app as mod

    monkeypatch.setenv("CELERY_QUEUES", "transcription")
    monkeypatch.setattr(sys, "argv", ["celery", "worker"])
    assert mod._worker_subscribes_to("transcription") is True
    assert mod._worker_subscribes_to("default") is False


def test_worker_subscribes_to_via_argv_long(monkeypatch):
    from app.task_queue import celery_app as mod

    monkeypatch.delenv("CELERY_QUEUES", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        ["celery", "worker", "--queues", "default"],
    )
    assert mod._worker_subscribes_to("default") is True
    assert mod._worker_subscribes_to("transcription") is False


def test_worker_subscribes_to_via_argv_equals(monkeypatch):
    from app.task_queue import celery_app as mod

    monkeypatch.delenv("CELERY_QUEUES", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        ["celery", "worker", "--queues=transcription,default"],
    )
    assert mod._worker_subscribes_to("transcription") is True
    assert mod._worker_subscribes_to("default") is True
    assert mod._worker_subscribes_to("nonexistent") is False


def test_worker_subscribes_to_via_argv_short_q(monkeypatch):
    from app.task_queue import celery_app as mod

    monkeypatch.delenv("CELERY_QUEUES", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        ["celery", "worker", "-Q", "transcription"],
    )
    assert mod._worker_subscribes_to("transcription") is True


def test_worker_subscribes_to_returns_false_when_no_queue_signal(monkeypatch):
    """No env, no CLI flag → returns False for everything. The init
    hook then takes the 'light worker' branch (no Whisper). Correct
    fail-safe: if an operator forgets to pass --queues, we'd rather
    skip the expensive model load than try to load it on a process
    that has no business doing transcription."""
    from app.task_queue import celery_app as mod

    monkeypatch.delenv("CELERY_QUEUES", raising=False)
    monkeypatch.setattr(sys, "argv", ["celery", "worker"])
    assert mod._worker_subscribes_to("transcription") is False
    assert mod._worker_subscribes_to("default") is False


def test_task_prerun_loads_only_the_runtime_required_by_task(monkeypatch):
    from app.task_queue import celery_app as mod

    calls: list[dict[str, bool]] = []
    monkeypatch.setattr(
        mod,
        "_ensure_worker_runtime",
        lambda **kwargs: calls.append(kwargs),
    )

    class Task:
        def __init__(self, name: str):
            self.name = name

    mod.ensure_task_runtime(task=Task("tasks.process_document_ingestion"))
    mod.ensure_task_runtime(task=Task("tasks.process_conversation_turn"))
    mod.ensure_task_runtime(task=Task("tasks.process_interview_analysis"))
    mod.ensure_task_runtime(task=Task("tasks.process_mock_interview_review"))
    mod.ensure_task_runtime(task=Task("tasks.refresh_model_catalog"))

    assert calls == [
        {"embedding": True, "reranker": False, "voice": False},
        {"embedding": True, "reranker": True, "voice": False},
        {"embedding": False, "reranker": False, "voice": True},
        {"embedding": False, "reranker": False, "voice": False},
        {"embedding": False, "reranker": False, "voice": False},
    ]
