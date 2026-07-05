"""Interview lifecycle services.

  interview_record_service  — CRUD + state transitions for InterviewRecord
                              + InterviewQA (the persistence layer for both
                              upload-source and mock-source interviews)
  record_admin              — router-facing owned-record operations: ownership
                              lookups, cancel, PATCH field updates, the cascade
                              delete, SSE poll snapshots. Distinct from
                              interview_record_service: that one is the
                              persistence CRUD layer; this one is the
                              per-request access/maintenance layer on top.
  analysis_intake           — POST /analyze intake orchestration: resume/JD
                              context resolution + text snapshots, record
                              creation, celery dispatch
  mock_interview_service    — Mock conducting layer: plan freezing
                              (generate_plan) + single-call per-turn generation
                              (generate_next_turn); no Runtime Director.
                              Post-interview scoring is NOT here — see
                              analysis_orchestrator.
  mock_runtime_service      — Lifecycle of the mock_interview_runtime row
                              (create / advance / set_status / delete)
  mock_flow                 — Mock-run orchestration: atomic start
                              (record+conversation+opening+runtime), answer
                              turn, review dispatch, abandon cascade
  analysis_orchestrator     — Unified pipeline that drives a record from
                              pending → completed (ASR → Q&A extraction →
                              per-question critique → synthesis); same code
                              path for both upload and mock sources

Dependency direction inside this package:
  analysis_orchestrator → interview_record_service
  analysis_intake       → interview_record_service (+ worker.tasks dispatch)
  mock_flow             → mock_interview_service + mock_runtime_service
                          + interview_record_service (+ worker.tasks dispatch)
  record_admin          → interview_record_service (status constants only)
  mock_interview_service is independent (no intra-package imports)
"""
from app.services.interview.analysis_orchestrator import analysis_orchestrator

__all__ = [
    "analysis_orchestrator",
]
