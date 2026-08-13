"""The single current final Offer for one JobOpportunity.

This is intentionally not a version collection. Earlier documents, messages,
and terms remain with their actual Artifact/FileAsset/Observation owners while
this row stores only the currently confirmed final terms and direct source
identities. Accepting or declining belongs to append-only ProcessEvent history,
so this model has no decision or process-outcome field.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)

from app.db.database import Base
from app.db.types import JSONValue as JSON
from app.db.types import UTCDateTime as DateTime
from app.db.types import utc_now


OFFER_SOURCE_KINDS = (
    "user_assertion",
    "observation",
    "tool_result",
    "provider_receipt",
    "artifact",
    "file_asset",
)


def generate_offer_id() -> str:
    return f"of_{uuid.uuid4().hex}"


class Offer(Base):
    """One mutable current-terms projection, unique per opportunity identity."""

    __tablename__ = "offers"
    __table_args__ = (
        UniqueConstraint(
            "job_opportunity_id",
            name="uq_offers_job_opportunity",
        ),
        UniqueConstraint(
            "user_id",
            "creation_operation_key",
            name="uq_offers_user_creation_operation",
        ),
        CheckConstraint(
            "last_source_kind IN "
            "('user_assertion', 'observation', 'tool_result', "
            "'provider_receipt', 'artifact', 'file_asset')",
            name="ck_offers_last_source_kind",
        ),
        CheckConstraint(
            "last_confirmation_source_kind IS NULL OR "
            "last_confirmation_source_kind IN "
            "('user_assertion', 'observation', 'tool_result', "
            "'provider_receipt', 'artifact', 'file_asset')",
            name="ck_offers_confirmation_source_kind",
        ),
        Index("ix_offers_user_updated", "user_id", "updated_at"),
    )

    id = Column(String(35), primary_key=True, default=generate_offer_id)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The real JobOpportunity Application Service validates this identity.
    # There is no placeholder model or polymorphic owner registry here.
    job_opportunity_id = Column(String(35), nullable=False, index=True)

    # Domain-typed by OfferTermsInput. Keeping the small common structure in
    # one snapshot permits diverse jurisdiction/company terms without dozens
    # of nullable mandatory columns. It is not a generic document payload.
    terms_json = Column(JSON, nullable=False)
    # Per top-level term key -> direct OfferSourceInput snapshot. Sources do
    # not become OfferVersion rows and do not increase a term's truth level.
    term_sources_json = Column(JSON, nullable=False, default=dict)
    # Direct source identity -> its exact wording and written/verbal status.
    # Multiple actual sources can coexist without pretending there is one
    # synthetic canonical original text.
    source_excerpts_json = Column(JSON, nullable=False, default=dict)

    # Creation identity remains stable after later current-term changes, so a
    # delayed retry of the original create is still idempotent.
    creation_operation_key = Column(String(128), nullable=False)
    creation_operation_fingerprint = Column(String(64), nullable=False)
    # Latest mutation fence. Full interaction/tool audit remains with its real
    # owner; this row does not duplicate a second audit/event log.
    last_operation_key = Column(String(128), nullable=False)
    last_operation_fingerprint = Column(String(64), nullable=False)

    last_source_kind = Column(String(32), nullable=False)
    last_source_identity = Column(String(256), nullable=False)
    last_source_version = Column(String(128), nullable=True)
    last_source_observed_at = Column(DateTime, nullable=False)

    # Populated only when an existing Offer changed after an explicit
    # supplement/replace decision. The candidate term sources remain in
    # term_sources_json; these columns identify the deciding assertion/readback.
    last_confirmation_source_kind = Column(String(32), nullable=True)
    last_confirmation_source_identity = Column(String(256), nullable=True)
    last_confirmation_source_version = Column(String(128), nullable=True)
    last_confirmation_observed_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)


__all__ = ["OFFER_SOURCE_KINDS", "Offer", "generate_offer_id"]
