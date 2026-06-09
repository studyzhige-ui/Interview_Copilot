"""Chat / dialogue support services — used by L1 (QA pipeline) and L3 (mock interview).

Submodules:
  - chat_history_service:        ``TranscriptService``, ``transcript_service``
  - context_assembly_pipeline:   ``ContextAssemblyPipeline``, ``context_pipeline``, helpers

Submodules are imported lazily (no eager re-exports here) — callers should
import from the specific submodule.
"""
