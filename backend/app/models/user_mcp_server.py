from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from app.db.database import Base
from app.db.types import JSONValue as JSON
from app.db.types import UTCDateTime as DateTime
from app.db.types import utc_now


class UserMCPServer(Base):
    __tablename__ = "user_mcp_servers"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_user_mcp_servers_user_name"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name = Column(String(64), nullable=False)
    transport = Column(String(24), nullable=False)
    url = Column(Text, nullable=True)
    command = Column(Text, nullable=True)
    args_json = Column(JSON, nullable=False, default=list)
    secrets_ciphertext = Column(Text, nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)
    last_status = Column(String(24), nullable=False, default="unchecked")
    last_error = Column(Text, nullable=True)
    tool_count = Column(Integer, nullable=False, default=0)
    checked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)
