"""Memory subsystem (v3 architecture).

Three long-term stores + the pipelines that maintain them:

  Stores:
    memory_document_service       — user_profile / learning_strategy markdown docs
    memory_ability_state_service  — per-topic mastery states

  Pipelines:
    realtime_extraction       — async, runs after every chat turn
    dreaming_worker           — sync Celery, per-record nightly synthesis
    post_turn_maintenance     — wires realtime_extraction into the QA loop

  Read entry-points:
    v3_context_loader         — universal + on-demand body loader

The old per-doc-type split (knowledge_doc / strategy_doc / habit_doc /
user_profile_doc) and the multi-row ``memory_items`` path are retired.
"""

from app.services.memory import (  # noqa: F401
    memory_ability_state_service,
    memory_document_service,
    realtime_extraction,
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
    # Stores
    "memory_document_service",
    "memory_ability_state_service",
    # Pipelines
    "realtime_extraction",
    "v3_context_loader",
    # Compaction (conversation → summary; historically lives in this package)
    "CompactionService",
    "compaction_service",
    # Post-turn maintenance
    "PostTurnMaintenanceService",
    "post_turn_maintenance_service",
]
