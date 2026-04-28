from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.db.database import Base
from app.models.chat import generate_uuid


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id = Column(String, primary_key=True, default=generate_uuid, index=True)
    user_id = Column(String, index=True, nullable=False)
    session_id = Column(String, index=True, nullable=False)
    mode = Column(String, nullable=False, default="function_calling")
    goal = Column(Text, nullable=False)
    status = Column(String, index=True, nullable=False, default="running")

    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at = Column(DateTime, nullable=True)

    final_answer = Column(Text, default="", nullable=False)
    error_message = Column(Text, nullable=True)
    budget_stop_reason = Column(String, nullable=True)

    steps_used = Column(Integer, default=0, nullable=False)
    tool_calls = Column(Integer, default=0, nullable=False)
    prompt_tokens = Column(Integer, default=0, nullable=False)
    completion_tokens = Column(Integer, default=0, nullable=False)
    total_latency_ms = Column(Float, default=0.0, nullable=False)

    steps = relationship("AgentStep", back_populates="run", order_by="AgentStep.step_index")


class AgentStep(Base):
    __tablename__ = "agent_steps"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    run_id = Column(String, ForeignKey("agent_runs.id"), index=True, nullable=False)
    step_index = Column(Integer, nullable=False)

    action_type = Column(String, nullable=False)  # tool_call | final_answer | budget_stop | error
    tool_name = Column(String, nullable=True)
    tool_call_id = Column(String, nullable=True)
    tool_args_json = Column(Text, default="{}", nullable=False)
    observation_json = Column(Text, default="{}", nullable=False)
    assistant_content = Column(Text, default="", nullable=False)

    is_error = Column(Boolean, default=False, nullable=False)
    latency_ms = Column(Float, default=0.0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    run = relationship("AgentRun", back_populates="steps")
