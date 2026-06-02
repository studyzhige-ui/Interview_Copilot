"""Lightweight metric counters for the v3 memory subsystem.

We don't have Prometheus on this stack — `telemetry_service` writes JSONL
events to ``metrics.jsonl`` and that's the agreed shape. This module is a
thin emit helper that namespaces memory events so an operator grepping
``metrics.jsonl`` can find them without parsing the whole stream.

Events we emit
==============

``memory.selection_llm_failed``
    The on-demand topic selection LLM call failed (timeout, malformed
    JSON, vendor error). The chat turn proceeded with the deterministic
    last_discussed_at fallback (see ``v3_context_loader``).

``memory.lock_degraded``
    The per-user memory lock could not be acquired (Redis down OR wait
    budget exhausted). Two writers may now race; patch protocol still
    prevents structural corruption but newly-added unrelated lines can
    be silently lost.

Both events are fire-and-forget — failures inside ``incr`` are swallowed
so the metric pipeline never breaks the path it observes.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)


_FILE_LOCK = Lock()


def _resolve_metrics_path() -> Path | None:
    """Compute the metrics output path lazily so a missing config /
    read-only volume never blocks import of the memory package.
    """
    try:
        from app.core.config import settings  # local import — cycles
        log_dir = Path(settings.LOG_DIR)
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir / "metrics.jsonl"
    except Exception as exc:  # noqa: BLE001
        logger.debug("memory metrics path unavailable: %s", exc)
        return None


def incr(event: str, *, value: int = 1, **labels: Any) -> None:
    """Append one metric event. Never raises.

    The shape mirrors ``telemetry_service.log_interaction_metrics`` —
    operators have one file to grep. Labels become top-level keys so
    a query like ``grep '"event":"memory.lock_degraded"' metrics.jsonl``
    yields parseable JSON lines.
    """
    payload = {
        "timestamp": datetime.now().isoformat(),
        "event": event,
        "value": value,
        **labels,
    }
    path = _resolve_metrics_path()
    if path is None:
        return
    try:
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        with _FILE_LOCK:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line)
    except Exception as exc:  # noqa: BLE001
        logger.debug("memory metrics emit failed (%s): %s", event, exc)


__all__ = ["incr"]
