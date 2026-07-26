"""Daily model-catalog refresh task (P6-K, light queue).

Why this is a Celery beat task and not a separate cron entry on the
host: we already run Celery beat for the dreaming nightly, the worker
image has the full FastAPI / RAG stack imported and ready, and using
beat means there's exactly one place to look for "what scheduled
work runs in this project" (``celery_app.py: beat_schedule``).

Why daily (not 24h TTL natural expiry): the natural-expiry path only
refreshes on the FIRST user request after the cache expires — and
that user pays the per-vendor /v1/models roundtrip latency (~200ms-2s
each, ~9 vendors in parallel = ~2s overall). A pre-warmed cache means
the morning's first user gets an instant /catalog response with the
day's freshest model list. The scheduled time (04:00) is well before
the workday so production users never collide with the refresh
window, and well after the dreaming batch (03:30) so the two heavy
jobs don't share the LLM/network at the same moment.
"""

import logging

from app.worker.celery_app import celery_app
from app.worker.tasks.runtime import run_async

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="tasks.refresh_model_catalog",
    # Each vendor's /v1/models call is bounded by the per-request 20s
    # httpx timeout inside the adapter base, plus one retry on
    # transient failure. With 9 vendors fanned out in parallel the
    # wall-clock worst case is ~40s; a 5-minute outer limit gives
    # plenty of headroom for slow upstreams without letting a hung
    # task starve the worker.
    time_limit=300,
    soft_time_limit=270,
)
def refresh_model_catalog_task(self):
    """Re-fetch each vendor's /v1/models and replace the Redis cache.

    Per-vendor failure is isolated — one vendor down doesn't blank
    the others, that vendor's slice falls back to its last-known-good
    snapshot. When ALL vendors fail (genuine network outage) the
    cache is NOT touched and we keep serving whatever was last good.
    """
    from app.core.model_catalog import repopulate_profile_cache
    from app.services.model_sources.pipeline import refresh_catalog

    async def _run():
        return await refresh_catalog()

    grouped = run_async(_run())
    # Keep this worker process's sync profile cache in sync so any
    # subsequent chat path in THIS process doesn't take a Redis round-trip.
    repopulate_profile_cache(grouped)

    per_vendor = {p: len(entries) for p, entries in grouped.items()}
    total = sum(per_vendor.values())
    empty_vendors = [p for p, n in per_vendor.items() if n == 0]
    logger.info(
        "refresh_model_catalog: total_models=%d per_vendor=%s",
        total,
        per_vendor,
    )
    if empty_vendors:
        # An empty vendor here usually means the deployment env is
        # missing that vendor's API key (no key → no /v1/models call
        # → empty list). Less commonly: the vendor's adapter
        # chat_filter dropped everything they returned.
        logger.warning(
            "refresh_model_catalog: %d vendor(s) returned 0 chat models "
            "(missing API key on cron host?): %s",
            len(empty_vendors),
            empty_vendors,
        )
    return {"per_vendor": per_vendor, "total": total}
