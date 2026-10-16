"""Editable workspace metadata and recoverable document drafts.

Formal documents remain ArtifactVersions; process facts remain ProcessEvents.
"""

from sqlalchemy import Column, ForeignKey, Integer, String, Text
from app.db.database import Base
from app.db.types import JSONValue, UTCDateTime, utc_now


class OpportunityDetails(Base):
    __tablename__ = "opportunity_details"
    opportunity_id = Column(
        String(35),
        ForeignKey("job_opportunities.id", ondelete="CASCADE"),
        primary_key=True,
    )
    notes = Column(Text, nullable=False, default="")
    contacts = Column(JSONValue, nullable=False, default=list)
    hidden_at = Column(UTCDateTime, nullable=True)


class DocumentDraft(Base):
    __tablename__ = "document_drafts"
    artifact_id = Column(
        String(128), ForeignKey("artifacts.id", ondelete="CASCADE"), primary_key=True
    )
    revision = Column(Integer, nullable=False, default=0)
    base_version_id = Column(String(128), nullable=False)
    title = Column(String(240), nullable=False)
    data = Column(JSONValue, nullable=False)
    last_save_key = Column(String(100), nullable=True)
    last_save_fingerprint = Column(String(64), nullable=True)
    updated_at = Column(UTCDateTime, nullable=False, default=utc_now, onupdate=utc_now)
