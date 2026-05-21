from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_process_init

from app.core.config import settings


# ── Sentry (per-worker) ─────────────────────────────────────────────────
# Each Celery worker process runs in its own interpreter, so we have to
# init the SDK after fork — the worker_process_init signal handler below
# does that. We only call sentry_sdk.init when SENTRY_DSN is configured.
def _init_sentry_for_worker() -> None:
    if not settings.SENTRY_DSN:
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.celery import CeleryIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
        from sentry_sdk.integrations.redis import RedisIntegration
    except ImportError:
        return
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.SENTRY_ENVIRONMENT,
        release=settings.SENTRY_RELEASE or None,
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
        integrations=[
            CeleryIntegration(monitor_beat_tasks=False),
            SqlalchemyIntegration(),
            RedisIntegration(),
        ],
        send_default_pii=False,
    )

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
    # Memory dreaming: nightly batch sweep at 03:30 Asia/Shanghai
    # (covers the "user is asleep" window). The task itself filters out
    # records where the user has been active in the last 4h — see
    # ``USER_INACTIVE_HOURS_FOR_BATCH`` in dreaming_worker.
    beat_schedule={
        "memory-dream-nightly-batch": {
            "task": "tasks.scan_and_dream_batch",
            "schedule": crontab(hour=3, minute=30),
        },
    },
)


@worker_process_init.connect
def init_worker_models(**kwargs):
    """Warm model resources when each Celery worker process starts."""
    import logging

    logger = logging.getLogger(__name__)
    # Sentry first so any subsequent init failure gets reported.
    _init_sentry_for_worker()
    # LangSmith next — must run BEFORE any LLM client is created (init_rag_settings
    # constructs them). No-op when LANGSMITH_TRACING isn't set in .env.
    from app.core.llm_tracing import setup_llm_tracing
    setup_llm_tracing()
    logger.info(">>> Celery worker started; warming LLM, RAG, and audio models...")

    from app.rag.embeddings import init_rag_settings
    from app.services.voice.audio_transcription_service import init_whisper_model

    init_rag_settings()
    init_whisper_model()
    logger.info(">>> Celery model warmup complete.")
