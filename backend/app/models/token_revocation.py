"""Durable single-use token ledger; cache eviction cannot restore authority."""

from sqlalchemy import Column, String
from app.db.types import UTCDateTime as DateTime

from app.db.database import Base


class TokenRevocation(Base):
    __tablename__ = "token_revocations"

    jti = Column(String(64), primary_key=True)
    expires_at = Column(DateTime, nullable=False, index=True)
