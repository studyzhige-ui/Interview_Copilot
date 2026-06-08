from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_process_init

from app.core.config import settings


celery_app = Celery(
    "interview_copilot_worker",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.worker.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,        # Hard kill at 60 min (transcription headroom).
    task_soft_time_limit=3540,   # 1 min before hard kill, raise SoftTimeLimitExceeded
                                 # so handlers can flush partial state.
    # ── Task routing ────────────────────────────────────────────────────
    # Two-queue split (introduced when the worker fleet was unified
    # against the user's "transcription is heavy, dreaming is light"
    # concern):
    #
    #   transcription queue  → heavy worker, loads Whisper (~1.5 GB GPU)
    #   default queue        → light worker, no Whisper (just LLM client)
    #
    # Operators run TWO worker processes — see docker-compose.yml's
    # worker-transcription / worker-light services. Both subscribe to
    # the same broker; queue subscription is the routing primitive.
    task_default_queue="default",
    task_routes={
        # ── Heavy: needs Whisper + diarization model ──
        "tasks.process_interview_analysis": {"queue": "transcription"},
        # ── Light: LLM / embedding / DB only ──
        "tasks.process_document_ingestion": {"queue": "default"},
        "tasks.dream_for_record": {"queue": "default"},
        "tasks.dream_for_user": {"queue": "default"},
        "tasks.scan_and_dream_batch": {"queue": "default"},
        # Catalog refresh is pure outbound HTTP — no GPU, no heavy
        # in-process model. Lands on the light queue alongside dreaming.
        "tasks.refresh_model_catalog": {"queue": "default"},
        # Outbox drain: object-storage / index cleanup. DB + storage I/O.
        "tasks.drain_outbox_jobs": {"queue": "default"},
    },
    # ── Reliability ─────────────────────────────────────────────────────
    # Default acks_late=True so a worker crash during a task re-queues the
    # message instead of silently dropping it. Tasks MUST be idempotent
    # under this flag — see worker/tasks.py for status-gated guards.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Avoid thundering-herd on transient backend outages.
    task_default_retry_delay=10,
    # ── Result backend hygiene ──────────────────────────────────────────
    # Without an explicit expiry, Celery keeps every result in Redis forever
    # → memory grows linearly. 24h is enough for the UI to poll status.
    result_expires=86400,
    # ── Broker transport ───────────────────────────────────────────────
    # visibility_timeout MUST exceed task_time_limit; otherwise Redis re-
    # delivers the message mid-execution and we get double-runs.
    broker_transport_options={"visibility_timeout": 3700},
    result_backend_transport_options={"visibility_timeout": 3700},
    # Don't prefetch jobs the worker can't process before visibility_timeout
    # — important with our --pool=solo single-task model.
    worker_prefetch_multiplier=1,
    # ── Beat schedule ───────────────────────────────────────────────────
    # Memory dreaming (Path B): nightly batch at 03:30 Asia/Shanghai.
    # Iterates eligible users (gate 1: >=24h since last_dreamed_at AND
    # gate 3: enough new chat activity), then dreams each user's
    # silent records. See ``dreaming_worker`` docstring for full gate
    # logic. This is the ONLY trigger — there's no per-record completion
    # hook, no per-turn hook (Path B over Path A decision in
    # docs/v3_memory_refactor_report.md).
    #
    # Model catalog refresh (P6-K): daily at 04:00 Asia/Shanghai. Hits
    # every vendor's /v1/models, drops + repopulates the global discovery
    # cache so the first user request of the day reads a warm entry
    # instead of paying the ~2s fan-out latency. Scheduled after the
    # dreaming batch (03:30) so the two heavy outbound-API jobs don't
    # share the network/LLM window. CRITICAL: this runs with no
    # user_id, so the cron host's env must have the API keys for any
    # vendor you want pre-warmed (per-user-only keys won't apply here).
    beat_schedule={
        "memory-dream-nightly-batch": {
            "task": "tasks.scan_and_dream_batch",
            "schedule": crontab(hour=3, minute=30),
        },
        "model-catalog-daily-refresh": {
            "task": "tasks.refresh_model_catalog",
            "schedule": crontab(hour=4, minute=0),
        },
        # Outbox drain: every minute, process due cross-system cleanup jobs
        # (delete orphaned objects / failed uploads, and — as later packages
        # register handlers — Milvus index + memory work).
        "outbox-drain-every-minute": {
            "task": "tasks.drain_outbox_jobs",
            "schedule": crontab(minute="*"),
        },
    },
)


def _worker_subscribes_to(queue_name: str) -> bool:
    """True iff this Celery worker process was started with --queues
    including ``queue_name``. Reads the parsed argv after Celery's
    own option parser has consumed it.

    Two ways the queue is signalled:
      * Explicit ``--queues transcription`` flag on the command line
      * ``CELERY_QUEUES`` env var set by the docker-compose service
        (a belt to the CLI braces — see worker-transcription /
        worker-light services for the wiring)

    If neither is set, the worker defaults to the configured
    ``task_default_queue`` ('default'), meaning it does NOT subscribe
    to ``transcription``.
    """
    import os
    import sys

    env = os.environ.get("CELERY_QUEUES", "").strip()
    if env and queue_name in {q.strip() for q in env.split(",")}:
        return True

    # Fall back to scanning argv for --queues/-Q.
    argv = sys.argv
    for i, arg in enumerate(argv):
        if arg in ("-Q", "--queues") and i + 1 < len(argv):
            return queue_name in {q.strip() for q in argv[i + 1].split(",")}
        if arg.startswith("--queues="):
            return queue_name in {q.strip() for q in arg.split("=", 1)[1].split(",")}
    return False


@worker_process_init.connect
def init_worker_models(**kwargs):
    """Warm model resources when each Celery worker process starts.

    Whisper is only loaded on workers that subscribe to the
    ``transcription`` queue — light workers (memory dreaming /
    document ingestion) save ~1.5 GB GPU by skipping it.
    """
    import logging

    logger = logging.getLogger(__name__)
    # LangSmith — must run BEFORE any LLM client is created (init_rag_settings
    # constructs them). No-op when LANGSMITH_TRACING isn't set in .env.
    from app.core.llm_tracing import setup_llm_tracing
    setup_llm_tracing()

    from app.rag.embeddings import init_rag_settings
    init_rag_settings()

    if _worker_subscribes_to("transcription"):
        logger.info(">>> Transcription worker — warming Whisper + diarization...")
        from app.services.voice.audio_transcription_service import init_whisper_model
        init_whisper_model()
        logger.info(">>> Transcription worker model warmup complete.")
    else:
        logger.info(
            ">>> Light worker (no Whisper). Subscribed queues: %s",
            kwargs.get("sender", "<unknown>"),
        )
