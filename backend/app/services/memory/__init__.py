"""Memory subsystem — extraction, compaction, retrieval, vector store.

A horizontal component used by both pipelines:
  - L1 (QA dialogue): post-turn maintenance runs after each chat turn.
  - L2 (ReAct agent): retrieval feeds context for tool-using agent runs.

Public surface (re-exported here for convenience):
  CompactionService            / compaction_service
  MemoryExtractionService      / memory_extraction_service
  MemoryRetrievalService       / memory_retrieval_service
  PostTurnMaintenanceService   / post_turn_maintenance_service
  MemoryVectorService          / memory_vector_service
"""

from app.services.memory.compaction_service import (  # noqa: F401
    CompactionService,
    compaction_service,
)
from app.services.memory.extraction_service import (  # noqa: F401
    MemoryExtractionService,
    memory_extraction_service,
)
from app.services.memory.post_turn_maintenance import (  # noqa: F401
    PostTurnMaintenanceService,
    post_turn_maintenance_service,
)
from app.services.memory.retrieval_service import (  # noqa: F401
    MemoryRetrievalService,
    memory_retrieval_service,
)
from app.services.memory.vector_service import (  # noqa: F401
    MemoryVectorService,
    memory_vector_service,
)

__all__ = [
    "CompactionService",
    "compaction_service",
    "MemoryExtractionService",
    "memory_extraction_service",
    "MemoryRetrievalService",
    "memory_retrieval_service",
    "PostTurnMaintenanceService",
    "post_turn_maintenance_service",
    "MemoryVectorService",
    "memory_vector_service",
]
