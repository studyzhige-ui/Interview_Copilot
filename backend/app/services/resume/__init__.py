"""Canonical personal-resume services.

Production reads and writes go through :mod:`resume_artifact_service` against
``Artifact(kind='resume')`` and its resume state/version rows. Pre-cut-over
tables remain migration/audit data and intentionally have no runtime service.
"""
