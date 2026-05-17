"""Enable LangSmith tracing for every LLM call we make.

Our LLM layer goes through ``llama_index.llms.openai_like.OpenAILike``
(see ``app.core.model_registry._build_llm_instance``), which internally
constructs ``openai.OpenAI`` / ``openai.AsyncOpenAI`` clients. LangSmith
provides ``langsmith.wrappers.wrap_openai`` to instrument those clients
without changing call sites.

Two layers of plumbing:

  1. **Module-level monkey-patch on import**: we replace ``openai.OpenAI``
     and ``openai.AsyncOpenAI`` factories so any client constructed AFTER
     ``setup_llm_tracing()`` runs is auto-wrapped. ``main.py`` calls this
     before any llama_index import so the ``from openai import AsyncOpenAI``
     line inside ``llama_index.llms.openai.base`` picks up the wrapped
     factory.

  2. **Per-instance fallback** via :func:`wrap_existing_client`: directly
     wraps an already-constructed ``AsyncOpenAI`` (idempotent — safe to
     call on an already-wrapped client). Used inside ``_build_llm_instance``
     so EVERY OpenAILike we hand out is guaranteed traceable, even if the
     monkey-patch was somehow circumvented (test reloads, plugin import
     ordering, etc.).

Both layers are no-ops when:

  - ``LANGSMITH_TRACING != "true"`` (zero overhead)
  - ``LANGSMITH_API_KEY`` empty (warn + skip)

Set these in ``.env`` to enable:

    LANGSMITH_API_KEY=lsv2_xxx
    LANGSMITH_PROJECT=interview-copilot-dev
    LANGSMITH_TRACING=true
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_PATCHED = False
_TRACING_ENABLED: bool | None = None  # None = not resolved yet


def _ensure_dotenv_loaded() -> None:
    """Load ``.env`` into ``os.environ`` ourselves.

    Why: ``main.py`` calls :func:`setup_llm_tracing` at module-import time,
    BEFORE ``app.core.config`` (which calls ``load_dotenv()``) gets
    imported transitively via the app's other modules. So in the FastAPI
    process, ``os.getenv("LANGSMITH_TRACING")`` returns ``None`` at our
    call time even though the value lives in ``.env``. The Celery worker
    doesn't have this problem because ``app.worker.celery_app`` imports
    ``app.core.config`` at module top before the ``worker_process_init``
    signal fires. To make both paths behave the same we just
    ``load_dotenv()`` ourselves here — it's idempotent.

    Important: we resolve the .env path from ``__file__`` (project_root/
    backend/app/core/llm_tracing.py → project_root/.env) rather than
    relying on CWD-relative search. uvicorn under ``dev.ps1`` runs with
    CWD=backend/; dotenv's default upward walk DOES find the file there,
    but other deployment shapes (containers, ``python -m app.main``)
    might not. Anchoring at __file__ removes that fragility.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    from pathlib import Path
    project_root = Path(__file__).resolve().parents[3]
    env_file = project_root / ".env"
    if env_file.exists():
        load_dotenv(env_file, override=False)
    else:
        # Last-resort fallback to the dotenv default search behaviour
        # (CWD-upwards) — non-fatal if even that turns up nothing.
        load_dotenv(override=False)


def _tracing_enabled() -> bool:
    """Memoize the LANGSMITH_TRACING + LANGSMITH_API_KEY check.

    We re-evaluate once per process; .env values don't change at runtime.
    """
    global _TRACING_ENABLED
    if _TRACING_ENABLED is not None:
        return _TRACING_ENABLED
    _ensure_dotenv_loaded()
    if (os.getenv("LANGSMITH_TRACING") or "").strip().lower() not in {"true", "1", "yes"}:
        _TRACING_ENABLED = False
        return False
    if not (os.getenv("LANGSMITH_API_KEY") or "").strip():
        logger.warning(
            "LANGSMITH_TRACING=true but LANGSMITH_API_KEY is empty — tracing disabled.",
        )
        _TRACING_ENABLED = False
        return False
    _TRACING_ENABLED = True
    return True


def setup_llm_tracing() -> bool:
    """Wire LangSmith into every OpenAI client created after this call.

    Returns True if tracing was activated, False otherwise. Safe to call
    multiple times — second and later calls are no-ops.
    """
    global _PATCHED
    if _PATCHED:
        return True

    if not _tracing_enabled():
        return False

    try:
        import openai
        from langsmith.wrappers import wrap_openai
    except ImportError as exc:
        logger.warning("LangSmith tracing requested but import failed: %s", exc)
        return False

    # Capture the unwrapped originals so the wrappers can still construct them.
    _orig_OpenAI = openai.OpenAI
    _orig_AsyncOpenAI = openai.AsyncOpenAI

    def _make_wrapped_sync(*args, **kwargs):
        return wrap_openai(_orig_OpenAI(*args, **kwargs))

    def _make_wrapped_async(*args, **kwargs):
        return wrap_openai(_orig_AsyncOpenAI(*args, **kwargs))

    openai.OpenAI = _make_wrapped_sync       # type: ignore[assignment]
    openai.AsyncOpenAI = _make_wrapped_async  # type: ignore[assignment]
    _PATCHED = True

    project = (os.getenv("LANGSMITH_PROJECT") or "default").strip()
    # ``print`` not ``logger.info`` — we run BEFORE main.py's
    # ``logging.basicConfig`` so any logger.info() at this point silently
    # dies at WARN default level. A bare print() is reliably visible in
    # uvicorn / celery stdout so the user can confirm tracing is live.
    print(
        f"[llm_tracing] LangSmith tracing enabled — every OpenAI-SDK call "
        f"now reported to project '{project}'.",
        flush=True,
    )
    return True


def wrap_existing_client(client: Any) -> Any:
    """Wrap an already-constructed ``AsyncOpenAI`` (or ``OpenAI``) in place.

    Idempotent: if the client is already wrapped (we detect this via the
    ``__ls_wrapped__`` marker attribute we set ourselves), it returns the
    client unchanged. No-op when tracing is disabled.

    This is the "belt + braces" complement to :func:`setup_llm_tracing`.
    The module-level monkey-patch covers clients constructed AFTER
    ``setup_llm_tracing()`` runs, but if anything constructs a client
    BEFORE that (transient race, plugin import ordering, hot-reload),
    we still want it traced. Call this on the client AFTER it's been
    built (e.g. via ``llm._get_aclient()``) and it'll be patched in
    place. Note: ``wrap_openai`` modifies the client by reassigning
    methods on it, so the patch survives across all subsequent calls.
    """
    if not _tracing_enabled() or client is None:
        return client
    if getattr(client, "__ls_wrapped__", False):
        return client
    try:
        from langsmith.wrappers import wrap_openai
    except ImportError:
        return client
    try:
        wrap_openai(client)
        setattr(client, "__ls_wrapped__", True)
        # Use print so this shows up even if logging hasn't been
        # initialized yet (e.g. when a model is built during
        # ``init_rag_settings`` inside the FastAPI lifespan).
        print(
            f"[llm_tracing] wrap_openai applied to {type(client).__name__} "
            f"(id={hex(id(client))})",
            flush=True,
        )
    except Exception as exc:  # noqa: BLE001 — never let tracing break the call
        logger.warning("wrap_openai failed on %s: %s", type(client).__name__, exc)
    return client


__all__ = ["setup_llm_tracing", "wrap_existing_client"]
