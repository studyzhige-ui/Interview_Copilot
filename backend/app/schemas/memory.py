"""Pydantic schemas for the memory HTTP endpoints."""
from __future__ import annotations

from pydantic import BaseModel, Field


class DocBodyRequest(BaseModel):
    # Optimistic-concurrency token (MEM-3): the updated_at returned by the
    # GET the edit was based on. Mismatch → 409.
    base_updated_at: str | None = None
    body: str = Field("", description="Full new body markdown.")


__all__ = ["DocBodyRequest"]
