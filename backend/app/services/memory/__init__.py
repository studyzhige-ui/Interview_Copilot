"""Memory subsystem (v3 architecture).

Three long-term stores + the pipelines that maintain them:

  Stores:
    memory_document_service       — user_profile / learning_strategy markdown docs
    memory_ability_state_service  — per-topic mastery states

  Pipelines (both run as persistent outbox jobs — see extraction_jobs):
    realtime_extraction       — per-turn extraction core (run_realtime_extraction)
    dreaming_worker           — per-record cross-session synthesis core
    extraction_jobs           — outbox glue: enqueue + handlers for the two jobs

  Realtime jobs are enqueued atomically by ``chat_history_service`` when it
  persists the assistant reply.

  Read entry-points:
    v3_context_loader         — universal + on-demand body loader

The old per-doc-type split (knowledge_doc / strategy_doc / habit_doc /
user_profile_doc) and the multi-row ``memory_items`` path are retired.
"""

from app.services.memory import (  # noqa: F401
    extraction_jobs,
    memory_ability_state_service,
    memory_document_service,
    realtime_extraction,
    v3_context_loader,
)

__all__ = [
    # Stores
    "memory_document_service",
    "memory_ability_state_service",
    # Pipelines
    "extraction_jobs",
    "realtime_extraction",
    "v3_context_loader",
]
