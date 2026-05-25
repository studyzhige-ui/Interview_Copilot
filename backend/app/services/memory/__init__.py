"""Memory subsystem (v3 architecture).

Four memory-doc types stored as markdown blobs, plus the realtime +
dreaming pipelines that maintain them:

  Docs:
    user_profile_doc_service  — single doc per user (identity / preferences)
    knowledge_doc_service     — per-topic understanding ("Redis", "TCP", ...)
    strategy_doc_service      — single doc, cross-topic answering methodology
    habit_doc_service         — single doc, stable practice routines + mindset

  Pipelines:
    realtime_extraction       — async, runs after every chat turn
    dreaming_worker           — sync Celery, per-record nightly synthesis
    post_turn_maintenance     — wires realtime_extraction into the QA loop

  Read entry-points:
    v3_context_loader         — universal + on-demand body loader

The legacy ``MemoryExtractionService`` / ``MemoryVectorService`` /
multi-row ``memory_items`` path is retired. The Phase-H back-compat
adapter ``MemoryRetrievalService`` was also deleted once all call sites
migrated to ``v3_context_loader``.
"""

from app.services.memory import (  # noqa: F401
    habit_doc_service,
    knowledge_doc_service,
    realtime_extraction,
    strategy_doc_service,
    user_profile_doc_service,
    v3_context_loader,
)
from app.services.memory.compaction_service import (  # noqa: F401
    CompactionService,
    compaction_service,
)
from app.services.memory.post_turn_maintenance import (  # noqa: F401
    PostTurnMaintenanceService,
    post_turn_maintenance_service,
)

__all__ = [
    # Doc services
    "habit_doc_service",
    "knowledge_doc_service",
    "strategy_doc_service",
    "user_profile_doc_service",
    # Pipelines
    "realtime_extraction",
    "v3_context_loader",
    # Compaction (session_state summarisation; unrelated to memory v3 but
    # historically lived in this package)
    "CompactionService",
    "compaction_service",
    # Post-turn maintenance
    "PostTurnMaintenanceService",
    "post_turn_maintenance_service",
]
