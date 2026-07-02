"""Chat / dialogue support services — used by L1 (QA pipeline) and L3 (mock interview).

Submodules:
  - chat_history_service:        ``TranscriptService``, ``transcript_service``
  - context_assembly_pipeline:   ``ContextAssemblyPipeline``, ``context_pipeline``, helpers
  - citation:                    inline ``[K#]`` citation extraction/validation
  - interview_reference:         interview-transcript reference block builder
  - session_task_service:        sync CRUD for session-scoped agent tasks

Submodules are imported lazily (no eager re-exports here) — callers should
import from the specific submodule.
"""
