import asyncio
import logging
import threading

from app.core.error_messages import humanize_error
from app.db.database import SessionLocal
from app.models.knowledge import KnowledgeDocument
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Reusable event loop for Celery workers
# ---------------------------------------------------------------------------
# Each Celery worker thread gets its own persistent event loop, avoiding the
# overhead of creating/destroying a loop on every task invocation.

_loop_local = threading.local()


def _get_worker_loop() -> asyncio.AbstractEventLoop:
    """Return a persistent event loop for the current worker thread."""
    loop = getattr(_loop_local, "loop", None)
    if loop is None or loop.is_closed():
        loop = asyncio.new_event_loop()
        _loop_local.loop = loop
    return loop


def run_async(coro):
    """Run an async coroutine inside a synchronous Celery task."""
    loop = _get_worker_loop()
    return loop.run_until_complete(coro)


@celery_app.task(
    bind=True,
    name="tasks.process_interview_analysis",
    autoretry_for=(ConnectionError, TimeoutError, OSError),
    retry_backoff=True,
    retry_backoff_max=120,
    retry_jitter=True,          # avoid thundering herd on transient outages
    max_retries=3,
    # Reliability: acks_late + time bounds. Keep both ceilings well below
    # the broker visibility_timeout (3700s) so a hung task is reclaimed and
    # re-delivered before Redis would re-deliver on its own.
    acks_late=True,
    time_limit=1800,            # 30 min hard
    soft_time_limit=1740,       # 1 min before hard kill
)
def process_interview_analysis(self, record_id: str, language: str = "zh"):
    """Run the unified analysis pipeline for an InterviewRecord.

    The orchestrator handles both source='upload' (audio → ASR → analysis)
    and source='mock' (composed transcript from QA buffer → analysis).

    ``language`` is a WhisperX language hint:
      * ``"zh"`` / ``"en"``: force the decoder to that language. Faster
        + much more accurate than auto-detect on clean monolingual audio.
      * ``"auto"``: let Whisper detect per clip. Use only for genuinely
        mixed-language recordings.
    Default ``"zh"`` matches the API's default and the UI default.

    Idempotent under retry: if the record is already in a terminal state
    (``completed``/``failed`` from a prior attempt that succeeded but whose
    ack we lost), short-circuit instead of re-running the entire pipeline.
    """
    from app.models.interview_record import InterviewRecord
    from app.services.interview.analysis_orchestrator import analysis_orchestrator
    from app.services.interview.interview_record_service import interview_record_service

    # ── Idempotency gate ────────────────────────────────────────────────
    db = SessionLocal()
    try:
        row = db.query(InterviewRecord).filter(InterviewRecord.id == record_id).first()
        if row is not None and row.status == "completed":
            logger.info(
                "[Task %s] InterviewRecord %s already completed; skipping re-run.",
                self.request.id, record_id,
            )
            return {"status": "skipped", "record_id": record_id, "reason": "already_completed"}
    finally:
        db.close()

    # Stash the celery task id so the cancel endpoint can revoke us.
    try:
        interview_record_service.set_status(
            record_id,
            "pending",
            celery_task_id=self.request.id,
        )
    except Exception:  # noqa: BLE001
        logger.warning("Failed to stash celery_task_id on %s", record_id)

    try:
        return analysis_orchestrator.run(record_id, language=language)
    except Exception as exc:  # noqa: BLE001
        # The orchestrator itself catches and writes STATUS_FAILED before
        # re-raising (see analysis_orchestrator.py:126), so in the common
        # case the record is already in the right state. The block below
        # is a *belt-and-braces* safety net:
        #
        #   1. If we're on the LAST retry attempt (Celery would discard
        #      the task next), make sure the record actually carries a
        #      "max retries exhausted" message so the user UI doesn't
        #      show a transient error from one of the middle attempts.
        #   2. If the orchestrator never got far enough to set FAILED
        #      (e.g. it crashed before its own try/except), force the
        #      status to FAILED here so the record never gets stuck in
        #      an intermediate state forever.
        retries_left = max(0, (self.max_retries or 0) - self.request.retries)
        is_final_attempt = retries_left == 0
        try:
            if is_final_attempt:
                # Humanize the user-facing message — the raw exception
                # (incl. the retry count) is already in the worker log above.
                interview_record_service.set_status(
                    record_id,
                    "failed",
                    error_message=f"分析失败：{humanize_error(exc)}"[:500],
                )
            else:
                # Mid-retry: only force-write if status is still in an
                # intermediate state (orchestrator didn't reach its
                # except branch). Don't overwrite a "completed" set by
                # a parallel success.
                row = SessionLocal()
                try:
                    rec = (
                        row.query(InterviewRecord)
                        .filter(InterviewRecord.id == record_id)
                        .first()
                    )
                    if rec is not None and rec.status not in {"completed", "failed"}:
                        interview_record_service.set_status(
                            record_id,
                            "failed",
                            error_message=f"分析失败：{humanize_error(exc)}"[:500],
                        )
                finally:
                    row.close()
        except Exception as recovery_exc:  # noqa: BLE001
            # Never let the recovery path mask the original error.
            logger.error(
                "Failed to mark interview %s as failed after task crash: %s "
                "(original error follows)",
                record_id, recovery_exc,
            )

        logger.error(
            "Interview analysis task failed for %s (attempt %d/%d): %s",
            record_id, self.request.retries + 1, self.max_retries + 1, exc,
        )
        raise


@celery_app.task(
    bind=True,
    name="tasks.process_document_ingestion",
    autoretry_for=(ConnectionError, TimeoutError, OSError),
    retry_backoff=True,
    retry_backoff_max=120,
    retry_jitter=True,
    max_retries=3,
    acks_late=True,
    time_limit=1200,            # 20 min hard
    soft_time_limit=1140,
)
def process_document_ingestion(self, document_id: str):
    """Download an uploaded document if needed and ingest it into Milvus/Docstore.

    Idempotency contract:
      * status='ready' with chunks already written → skip
      * status='processing'/'failed' → fresh attempt; existing Milvus rows
        for ``ref_doc_ids`` (if any) are best-effort deleted first to avoid
        duplicate chunks on retry. Failure to delete is non-fatal.
    """
    import json
    import os
    import tempfile

    from app.rag.ingestion import ingest_document
    from app.services.knowledge.knowledge_service import dump_json_list
    from app.services.storage_service import download_file_from_s3

    db = SessionLocal()
    document = None
    local_file_path = None
    is_temp_file = False

    try:
        document = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == document_id).first()
        if document is None:
            return {"status": "failed", "error": f"Knowledge document not found: {document_id}"}
        if not document.upload or document.upload.user_id != document.user_id:
            raise ValueError("Knowledge upload owner does not match document owner")
        if document.upload.purpose != "knowledge_document":
            raise ValueError("Knowledge document upload has invalid purpose")
        if document.status not in {"processing", "failed"}:
            return {"status": "skipped", "document_id": document_id, "current_status": document.status}

        # If this is a retry of a partially-succeeded attempt (we crashed
        # between Milvus insert and DB commit), log it. A Phase-3 follow-up
        # will delete stale Milvus rows for ``document.ref_doc_ids`` to avoid
        # duplicate chunks; for now status-gate is the main reliability win
        # and duplicates are filtered at query time by document_id.
        if self.request.retries > 0 and document.ref_doc_ids:
            stale_count = 0
            try:
                stale_count = len(json.loads(document.ref_doc_ids) or [])
            except json.JSONDecodeError:
                pass
            logger.warning(
                "[Task %s] Retry attempt #%d for document %s; %d stale ref_doc_ids "
                "from prior attempt may produce duplicates (filtered at query time).",
                self.request.id, self.request.retries, document_id, stale_count,
            )

        if not document.storage_uri.startswith("s3://"):
            raise ValueError("Knowledge ingestion only accepts owned S3 uploads")

        expected_prefix = f"uploads/{document.user_id}/{document.upload_id}/"
        if not document.object_key.startswith(expected_prefix):
            raise ValueError("Knowledge upload object key does not match owner prefix")

        logger.info("[Task %s] Downloading S3 document for RAG ingestion.", self.request.id)
        _, ext = os.path.splitext(document.object_key)
        tmp_fd, local_file_path = tempfile.mkstemp(suffix=ext)
        os.close(tmp_fd)

        try:
            download_file_from_s3(document.storage_uri, local_file_path)
            is_temp_file = True
            logger.info("[Task %s] Document downloaded to %s", self.request.id, local_file_path)
        except Exception:
            if os.path.exists(local_file_path):
                os.unlink(local_file_path)
            raise

        logger.info("[Task %s] Starting RAG ingestion into Milvus/Docstore.", self.request.id)
        result = run_async(
            ingest_document(
                local_file_path,
                document.source_type,
                document.user_id,
                document_id=document.id,
                upload_id=document.upload_id,
                category=document.category,
            )
        )

        if result and result.get("success"):
            document.status = "ready"
            document.chunk_count = int(result.get("chunk_count") or 0)
            document.ref_doc_ids = dump_json_list(result.get("ref_doc_ids") or [])
            document.error_message = None
            db.add(document)
            db.commit()
            logger.info("[Task %s] Document ingestion completed.", self.request.id)
            return {"status": "success", "document_id": document_id}

        document.status = "failed"
        document.error_message = "Empty or unparseable document"
        db.add(document)
        db.commit()
        logger.warning("[Task %s] Document was empty or unparseable.", self.request.id)
        return {"status": "failed", "error": "Empty or unparseable document"}

    except Exception as exc:
        # Distinguish mid-retry vs final-attempt the same way
        # process_interview_analysis does. Mid-retry: a transient
        # status='failed' would make the UI flash "failed" between
        # retries; tag it as "retrying" instead so the user sees a
        # consistent in-progress signal until we give up for good.
        retries_left = max(0, (self.max_retries or 0) - self.request.retries)
        is_final_attempt = retries_left == 0
        if document is not None:
            try:
                if is_final_attempt:
                    document.status = "failed"
                    # Humanize the terminal user-facing message (e.g. a 402
                    # balance error during embedding); raw detail is logged.
                    document.error_message = f"导入失败：{humanize_error(exc)}"[:500]
                else:
                    # Don't mark as terminal "failed" mid-retry — leave
                    # status='processing' (the prior set_status from line
                    # 144's gate) and surface the latest error message
                    # for debug visibility.
                    document.error_message = (
                        f"Attempt {self.request.retries + 1} crashed; will retry. "
                        f"{type(exc).__name__}: {exc}"
                    )[:500]
                db.add(document)
                db.commit()
            except Exception as recovery_exc:  # noqa: BLE001
                logger.error(
                    "Failed to update document %s status after task crash: %s",
                    document.id, recovery_exc,
                )
        logger.error(
            "[Task %s] RAG ingestion task failed (attempt %d/%d): %s",
            self.request.id, self.request.retries + 1, self.max_retries + 1, exc,
        )
        raise

    finally:
        if is_temp_file and os.path.exists(local_file_path):
            os.unlink(local_file_path)
            logger.info("[Task %s] Removed temporary document: %s", self.request.id, local_file_path)
        db.close()


# ══════════════════════════════════════════════════════════════════════
# Memory dreaming tasks
# ══════════════════════════════════════════════════════════════════════


@celery_app.task(
    bind=True,
    name="tasks.dream_for_record",
    autoretry_for=(ConnectionError, TimeoutError, OSError),
    retry_backoff=True,
    retry_backoff_max=120,
    retry_jitter=True,
    max_retries=2,
    acks_late=True,
    time_limit=600,
    soft_time_limit=540,
)
def dream_for_record_task(self, record_id: str):
    """Run one dreaming pass for a single interview record.

    Idempotent: ``dream_for_record`` re-checks ``last_dreamed_at`` under
    the per-user lock, so a double-fire is harmless (the second run
    sees no new content and bumps the cursor without an LLM call).
    """
    from app.services.memory.dreaming_worker import dream_for_record

    summary = dream_for_record(record_id)
    if summary.get("error"):
        # RuntimeError is NOT in autoretry_for above (which only covers
        # transient network errors). This raise therefore terminates
        # the task without a Celery-level retry — soft failures (LLM
        # timeout / hard_failure) rely on the next nightly scan to
        # reconsider the record, NOT immediate Celery retry.
        raise RuntimeError(f"dream failed: {summary['error']}")
    return summary


@celery_app.task(
    bind=True,
    name="tasks.scan_and_dream_batch",
    time_limit=900,
    soft_time_limit=840,
)
def scan_and_dream_batch_task(self):
    """Nightly batch entry — Path B autoDream.

    Wakes up via Celery Beat at 03:30 Asia/Shanghai. Walks every user
    that passes the per-user gates (>=24h cursor + activity volume)
    and dreams each user's silent records, then bumps the user's
    cursor. See ``dreaming_worker`` module docstring for the full gate
    table.

    Per-user work is dispatched as a dedicated ``dream_for_user_task``
    so a slow LLM call on one user doesn't block another, and Celery's
    soft_time_limit / retry policy applies per-user (not per-batch).
    """
    from app.services.memory.dreaming_worker import select_dreamable_users

    users = select_dreamable_users(limit=200)
    dispatched = 0
    for uid in users:
        try:
            dream_for_user_task.delay(uid)
            dispatched += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "scan_and_dream_batch: dispatch failed for user=%s: %s",
                uid, exc,
            )
    logger.info(
        "scan_and_dream_batch: dispatched %d dream tasks (of %d eligible users)",
        dispatched, len(users),
    )
    return {"dispatched": dispatched, "users": len(users)}


@celery_app.task(
    bind=True,
    name="tasks.dream_for_user",
    autoretry_for=(ConnectionError, TimeoutError, OSError),
    retry_backoff=True,
    retry_backoff_max=120,
    retry_jitter=True,
    max_retries=2,
    acks_late=True,
    time_limit=1200,
    soft_time_limit=1140,
)
def dream_for_user_task(self, user_id: str):
    """Run all of a user's pending dreams + bump cursor.

    Per-record dream is delegated to ``dream_for_record`` (synchronous;
    no separate Celery dispatch — we want the cursor bump to happen
    AFTER all this user's records are processed, atomically observable
    from the user's perspective). If any individual record fails, log
    and continue — partial progress is better than re-doing finished
    records on the next batch.
    """
    from datetime import datetime
    from app.services.memory.dreaming_worker import (
        bump_user_last_dreamed_at,
        dream_for_record,
        select_records_for_user,
    )

    # Snapshot scan-start time BEFORE the per-record loop. The cursor
    # is bumped to THIS timestamp at the end, not to "now after the
    # dream finished" — otherwise any chat message arriving during the
    # multi-minute dream loop would have created_at < bump_time and
    # silently get dropped from the next nightly's gate-3 count.
    # Review found this as M1.
    scan_started_at = datetime.utcnow()

    records = select_records_for_user(user_id, limit=50)
    summary = {"user_id": user_id, "candidates": len(records), "dreamed": 0, "errors": 0}
    for rec in records:
        try:
            r = dream_for_record(rec.id)
            if r.get("error"):
                summary["errors"] += 1
                logger.warning(
                    "dream_for_user: record %s for user %s failed: %s",
                    rec.id, user_id, r["error"],
                )
            else:
                summary["dreamed"] += 1
        except Exception as exc:  # noqa: BLE001
            summary["errors"] += 1
            logger.exception(
                "dream_for_user: record %s for user %s crashed: %s",
                rec.id, user_id, exc,
            )
    # Bump cursor unconditionally — gate 3 (volume) is what guards
    # against firing this task in the first place. Whether or not each
    # individual record produced patches, the "consolidation pass for
    # this user" has happened and the next nightly should wait for new
    # activity before firing again.
    bump_user_last_dreamed_at(user_id, at=scan_started_at)
    logger.info(
        "dream_for_user: user=%s candidates=%d dreamed=%d errors=%d",
        user_id, summary["candidates"], summary["dreamed"], summary["errors"],
    )
    return summary


# ── Daily model catalog refresh (P6-K) ─────────────────────────────────
# Why this is a Celery beat task and not a separate cron entry on the
# host: we already run Celery beat for the dreaming nightly, the worker
# image has the full FastAPI / RAG stack imported and ready, and using
# beat means there's exactly one place to look for "what scheduled
# work runs in this project" (``celery_app.py: beat_schedule``).
#
# Why daily (not 24h TTL natural expiry): the natural-expiry path only
# refreshes on the FIRST user request after the cache expires — and
# that user pays the per-vendor /v1/models roundtrip latency (~200ms-2s
# each, ~9 vendors in parallel = ~2s overall). A pre-warmed cache means
# the morning's first user gets an instant /catalog response with the
# day's freshest model list. The scheduled time (04:00) is well before
# the workday so production users never collide with the refresh
# window, and well after the dreaming batch (03:30) so the two heavy
# jobs don't share the LLM/network at the same moment.
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
    from app.core.model_registry import repopulate_profile_cache
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
        total, per_vendor,
    )
    if empty_vendors:
        # An empty vendor here usually means the deployment env is
        # missing that vendor's API key (no key → no /v1/models call
        # → empty list). Less commonly: the vendor's adapter
        # chat_filter dropped everything they returned.
        logger.warning(
            "refresh_model_catalog: %d vendor(s) returned 0 chat models "
            "(missing API key on cron host?): %s",
            len(empty_vendors), empty_vendors,
        )
    return {"per_vendor": per_vendor, "total": total}


@celery_app.task(
    bind=True,
    name="tasks.drain_outbox_jobs",
    # Cleanup work is small and bounded (object deletes, index drops). A short
    # outer limit keeps a hung external call from pinning the worker.
    time_limit=120,
    soft_time_limit=110,
)
def drain_outbox_jobs(self):
    """Process due ``outbox_jobs`` — reliable cross-system side effects.

    Runs every minute (beat). Claims a batch of due jobs and runs each
    registered handler with retry/backoff. Idempotent and lock-guarded, so
    overlapping runs are safe.
    """
    from app.db.database import SessionLocal
    from app.services.uploads.outbox_service import run_due_outbox_jobs
    # Import for side effect: registers the Milvus ability-index handlers
    # (upsert/delete_memory_ability_index) before any job is claimed.
    import app.services.memory.ability_outbox  # noqa: F401

    with SessionLocal() as db:
        processed = run_due_outbox_jobs(db)
    if processed:
        logger.info("drain_outbox_jobs: processed %d job(s)", processed)
    return {"processed": processed}
