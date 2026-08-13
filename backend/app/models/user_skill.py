from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from app.db.types import JSONValue as JSON

from app.db.database import Base
from app.db.types import UTCDateTime as DateTime
from app.db.types import utc_now


class UserSkill(Base):
    __tablename__ = "user_skills"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_user_skills_user_name"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name = Column(String(64), nullable=False)
    description = Column(String(500), nullable=False)
    content = Column(Text, nullable=False)
    revision = Column(Integer, nullable=False, default=1, server_default="1")
    content_hash = Column(String(64), nullable=False, default="")
    source = Column(String(32), nullable=False, default="user", server_default="user")
    applicable_profiles_json = Column(JSON, nullable=False, default=list)
    required_tools_json = Column(JSON, nullable=False, default=list)
    allowed_tools_json = Column(JSON, nullable=False, default=list)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)


class UserSkillResource(Base):
    __tablename__ = "user_skill_resources"
    __table_args__ = (
        UniqueConstraint("skill_id", "path", name="uq_user_skill_resources_path"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    skill_id = Column(
        Integer,
        ForeignKey("user_skills.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    path = Column(String(255), nullable=False)
    kind = Column(String(32), nullable=False)
    content = Column(Text, nullable=False)
    content_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)
