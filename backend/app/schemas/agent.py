"""Pydantic schemas for the agent / react-agent HTTP endpoints."""

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., description="Message for normal agent chat")


class ReactAgentRequest(BaseModel):
    message: str = Field(..., description="Goal for ReAct tool-using agent")
    include_trace: bool = Field(default=False, description="Whether to return tool trace")


__all__ = ["ChatRequest", "ReactAgentRequest"]
