"""Versioned shape of durable manual ingress and read-only recovery receipts."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.interview_invitation import (
    ConfirmInterviewInvitation,
    ConfirmInterviewInvitationResult,
)


class SubmissionKey(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=1, max_length=200)


class InvitationSubmissionReceipt(SubmissionKey):
    status: Literal["not_received", "pending", "committed", "rejected", "cancelled"]
    command: ConfirmInterviewInvitation | None = None
    result: ConfirmInterviewInvitationResult | None = None

    @model_validator(mode="after")
    def check_receipt(self):
        if self.status == "pending":
            if (
                self.command is None
                or self.command.actor_kind != "user"
                or self.command.idempotency_key != self.idempotency_key
                or self.result is not None
            ):
                raise ValueError("pending receipt requires its exact user command")
        elif self.status == "committed":
            if (
                self.result is None
                or self.command is not None
                or self.result.verification.conclusion not in {"verified", "reconciled"}
            ):
                raise ValueError("committed receipt requires verified operation result")
        elif self.command is not None or self.result is not None:
            raise ValueError("non-committed receipt cannot claim a result")
        return self
