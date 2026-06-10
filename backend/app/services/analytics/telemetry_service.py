import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)

LOG_DIR = Path(settings.LOG_DIR)
LOG_FILE = LOG_DIR / "metrics.jsonl"

LOG_DIR.mkdir(parents=True, exist_ok=True)


def _write_log_sync(log_data: dict):
    """Write one telemetry event without blocking the main coroutine."""
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_data, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to write telemetry event: %s", exc)


async def log_interaction_metrics(
    session_id: str,
    user_id: str,
    latency: float,
    prompt_tokens: int,
    completion_tokens: int,
    retrieval_attempted: bool,
    retrieval_hit: bool,
    stop_reason: str | None = None,
    planner_failed: bool = False,
    fallback_used: bool = False,
    empty_reason: str | None = None,
):
    """Persist interaction metrics without affecting the API response path.

    ``stop_reason`` is populated by the L2 agent strategy (budget stop
    reason) and is None for L1 chat turns — kept so log post-mortems
    can correlate a tail-latency outlier with its budget exhaust
    reason. LangSmith covers the rest of the per-step trace surface.

    The RAG degradation fields mirror the turn's RetrievalState so online
    sampling can aggregate planner_failure_rate / reranker fallback_rate /
    empty_reason without a second trace path (evaluation plan §3.3.6 —
    field names kept identical to the offline trace schema).
    """
    try:
        timestamp = datetime.now().isoformat()
        log_payload = {
            "timestamp": timestamp,
            "session_id": session_id,
            "user_id": user_id,
            "latency_seconds": round(latency, 4),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "retrieval_attempted": retrieval_attempted,
            "retrieval_hit": retrieval_hit,
            "planner_failed": planner_failed,
            "fallback_used": fallback_used,
            "empty_reason": empty_reason,
            "stop_reason": stop_reason,
        }

        await asyncio.to_thread(_write_log_sync, log_payload)

        logger.debug(
            ">> [Telemetry] [%s] Latency: %.2fs | Tokens: %s+%s | RAG Hit: %s",
            session_id,
            latency,
            prompt_tokens,
            completion_tokens,
            retrieval_hit,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Telemetry event dropped: %s", exc)
