"""Interview lifecycle services.

  interview_record_service  — CRUD + state transitions for InterviewRecord
                              + InterviewQA (the persistence layer for both
                              upload-source and mock-source interviews)
  mock_interview_service    — Runtime Director: brief / per-turn director /
                              history summarizer; the conducting LLM layer
                              for AI mock interviews (post-interview
                              scoring is NOT here — see analysis_orchestrator)
  analysis_orchestrator     — Unified pipeline that drives a record from
                              pending → completed (ASR → Q&A extraction →
                              per-question critique → synthesis); same code
                              path for both upload and mock sources

Dependency direction inside this package:
  analysis_orchestrator → interview_record_service
  mock_interview_service is independent (no intra-package imports)
"""
from app.services.interview.analysis_orchestrator import analysis_orchestrator

__all__ = [
    "analysis_orchestrator",
]
