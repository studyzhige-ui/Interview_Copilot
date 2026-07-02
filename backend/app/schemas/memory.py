"""Pydantic schemas for the memory HTTP endpoints."""
from __future__ import annotations

from pydantic import BaseModel, Field


class DocBodyRequest(BaseModel):
    body: str = Field("", description="Full new body markdown.")


__all__ = ["DocBodyRequest"]
