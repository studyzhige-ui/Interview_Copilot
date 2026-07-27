import logging
from threading import Lock

from celery import Celery
from celery.schedules import crontab
from celery.signals import task_prerun, worker_process_init

from app.core.config import settings

# Workers run with --loglevel=info and Celery hijacks the root logger, so
# httpx's per-request INFO line ("HTTP Request: GET <full URL> ...") would
# print Gemini's url-key API key on every nightly catalog refresh. The
# application already logs redacted fetch errors itself (vendors/base.py
# _redact); the library's request log adds nothing but the leak.
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


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
    # Opt into the Celery 6.0 default explicitly (silences the
    # CPendingDeprecationWarning): keep retrying the broker connection during
    # worker startup so a transient Redis hiccup at boot doesn't abort the
    # worker. This is the forward-compatible fix — no Celery major-version bump.
    broker_connection_retry_on_startup=True,
    task_track_started=True,
    task_time_limit=3600,  # Hard kill at 60 min (transcription headroom).
    task_soft_time_limit=3540,  # 1 min before hard kill, raise SoftTimeLimitExceeded
    # so handlers can flush partial state.
    # ── Task routing ────────────────────────────────────────────────────
    # Four queues keep incompatible workloads from blocking one another:
    #
    #   turns         → long-lived chat/Agent turns with reconnectable SSE
    #   transcription → serialized ASR/diarization, loads voice models
    #   pipeline      → serialized parsing/embedding/durable outbox work
    #   default       → short control, catalog and scheduling jobs
    #
    # Container deployments run one process per queue; local scripts run one
    # solo worker subscribed to all three. Queue subscription is the routing
    # primitive in both cases.
    task_default_queue="default",
    task_routes={
        "tasks.process_conversation_turn": {"queue": "turns"},
        # ── Heavy: needs Whisper + diarization model ──
        "tasks.process_interview_analysis": {"queue": "transcription"},
        # ── Durable content pipeline: parsing / embedding / outbox handlers ──
        "tasks.process_document_ingestion": {"queue": "pipeline"},
        "tasks.process_resume_parse": {"queue": "pipeline"},
        "tasks.drain_outbox_jobs": {"queue": "pipeline"},
        # ── Short control/background jobs ──
        "tasks.dream_for_user": {"queue": "default"},
        "tasks.scan_and_dream_batch": {"queue": "default"},
        "tasks.process_mock_interview_review": {"queue": "default"},
        # Catalog refresh is pure outbound HTTP — no GPU, no heavy
        # in-process model. Lands on the light queue alongside dreaming.
        "tasks.refresh_model_catalog": {"queue": "default"},
        # Zombie sweeper: pure DB scan.
        "tasks.sweep_stale_interview_records": {"queue": "default"},
        "tasks.sweep_stale_pipeline_records": {"queue": "default"},
        "tasks.sweep_orphan_file_assets": {"queue": "default"},
    },
    # ── Reliability ─────────────────────────────────────────────────────
    # Default acks_late=True so a worker crash during a task re-queues the
    # message instead of silently dropping it. Tasks MUST be idempotent
    # under this flag — see the modules under worker/tasks/ for the
    # status-gated guards.
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
    # Memory consolidation: nightly batch at 03:30 Asia/Shanghai.
    # Iterates eligible users (gate 1: >=24h since last_dreamed_at AND
    # gate 3: enough new chat activity), then dreams each user's
    # silent records. See ``dreaming_worker`` docstring for full gate
    # logic. This is the ONLY trigger — there's no per-record completion
    # hook, no per-turn hook (see the
    # ``dreaming_worker`` module docstring).
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
        # Zombie sweeper: records whose broker message was lost outright
        # (e.g. Redis restart without persistence) never move again —
        # this is the terminal-state guarantee of last resort. Every 10
        # minutes; the task itself only sweeps rows stale >2h.
        "stale-record-sweep": {
            "task": "tasks.sweep_stale_interview_records",
            "schedule": crontab(minute="*/10"),
        },
        "stale-pipeline-sweep": {
            "task": "tasks.sweep_stale_pipeline_records",
            "schedule": crontab(minute="5-59/10"),
        },
        # Daily orphan-upload cleanup (UP-3) — off-peak, after the memory
        # dreaming batch.
        "uploads-sweep-orphans-daily": {
            "task": "tasks.sweep_orphan_file_assets",
            "schedule": crontab(hour=4, minute=20),
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
        (a belt to the CLI braces — see the worker services in compose)

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


_runtime_lock = Lock()
_embedding_runtime_ready = False
_reranker_runtime_ready = False
_voice_runtime_ready = False


def _ensure_worker_runtime(
    *,
    embedding: bool = False,
    reranker: bool = False,
    voice: bool = False,
) -> None:
    """Lazily initialize only the models required by the current queue/task."""
    global _embedding_runtime_ready, _reranker_runtime_ready, _voice_runtime_ready
    with _runtime_lock:
        # Must run before any LLM client is created. Idempotent when disabled.
        from app.core.llm_tracing import setup_llm_tracing

        setup_llm_tracing()

        if embedding and not _embedding_runtime_ready:
            from app.rag.embeddings import init_rag_settings

            # Workers never generate user-facing answers, so do not resolve or
            # warm the user's/default answer model here.
            init_rag_settings(include_primary_llm=False)
            _embedding_runtime_ready = True
            logger.info(">>> Worker embedding runtime ready.")

        if reranker and not _reranker_runtime_ready:
            from app.rag.retriever import init_reranker

            init_reranker()
            _reranker_runtime_ready = True
            logger.info(">>> Worker reranker runtime ready.")

        if voice and not _voice_runtime_ready:
            from app.services.voice.audio_transcription_service import (
                init_whisper_model,
            )

            init_whisper_model()
            _voice_runtime_ready = True
            logger.info(">>> Worker voice runtime ready.")


@worker_process_init.connect
def init_worker_models(**kwargs):
    """Warm only queue-specific heavyweight resources.

    ``task_prerun`` below is the correctness fallback for thread/solo pools
    where process-init signal behaviour differs.
    """
    from app.core.llm_tracing import setup_llm_tracing

    setup_llm_tracing()
    if _worker_subscribes_to("turns"):
        logger.info(">>> Conversation worker — warming RAG runtime...")
        _ensure_worker_runtime(embedding=True, reranker=True)
    elif _worker_subscribes_to("transcription"):
        logger.info(">>> Transcription worker — warming Whisper + diarization...")
        _ensure_worker_runtime(voice=True)
    elif _worker_subscribes_to("pipeline"):
        logger.info(">>> Pipeline worker — warming embedding runtime...")
        _ensure_worker_runtime(embedding=True)
    else:
        logger.info(">>> Control worker — no heavyweight model warmup.")


_EMBEDDING_TASKS = {
    "tasks.process_conversation_turn",
    "tasks.process_document_ingestion",
    "tasks.drain_outbox_jobs",
}


@task_prerun.connect
def ensure_task_runtime(task=None, **kwargs):
    """Guarantee task prerequisites even when process-init did not fire."""
    task_name = getattr(task, "name", "")
    _ensure_worker_runtime(
        embedding=task_name in _EMBEDDING_TASKS,
        reranker=task_name == "tasks.process_conversation_turn",
        voice=task_name == "tasks.process_interview_analysis",
    )
