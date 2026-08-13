from sqlalchemy import Column, ForeignKey, Integer, String, UniqueConstraint

from app.db.database import Base
from app.db.types import UTCDateTime as DateTime
from app.db.types import utc_now


class AgentTaskSkillBinding(Base):
    """Version-pinned Skill activation for one explicit AgentTask."""

    __tablename__ = "agent_task_skill_bindings"
    __table_args__ = (
        UniqueConstraint(
            "agent_task_id",
            "skill_name",
            name="uq_agent_task_skill_bindings_task_name",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_task_id = Column(
        String(35),
        ForeignKey("agent_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    skill_id = Column(
        Integer,
        ForeignKey("user_skills.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    skill_name = Column(String(64), nullable=False)
    skill_source = Column(String(32), nullable=False)
    skill_revision = Column(Integer, nullable=False)
    content_hash = Column(String(64), nullable=False)
    activated_at = Column(DateTime, nullable=False, default=utc_now)
