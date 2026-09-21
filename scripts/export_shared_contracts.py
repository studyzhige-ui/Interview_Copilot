"""Export shared protocol schemas without starting the app or opening a database.

The Pydantic DTOs are authoritative. Validation and serialization are generated
separately: defaults may be omitted by clients but are present in API responses.
Run with --check in CI; use the pinned openapi-typescript development tool to
regenerate frontend/src/types/generated/shared-protocols.ts after an edit.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from pydantic.json_schema import models_json_schema  # noqa: E402

from app.schemas.agent_interaction import (  # noqa: E402
    AgentInteractionView,
    PendingInteractionProjection,
    ResolveInteractionRequest,
    ResolveInteractionResponse,
)
from app.schemas.career_activity import CareerActivityEvent  # noqa: E402
from app.schemas.client_action import (  # noqa: E402
    MockClientActionRequest,
    MockClientActionResolutionResponse,
    MockClientActionResultRequest,
    MockClientActionTakeoverRequest,
    MockClientActionView,
)
from app.schemas.context_package import ContextPackage  # noqa: E402
from app.schemas.interview_invitation import (  # noqa: E402
    ConfirmInterviewInvitation,
    ConfirmInterviewInvitationResult,
    FactConfirmationRequest,
    FactConfirmationResolution,
    InterviewInvitationCandidateFacts,
    InterviewInvitationHandoffView,
    VerificationView,
)
from app.schemas.invitation_submission import (  # noqa: E402
    InvitationSubmissionReceipt,
    SubmissionKey,
)

from app.schemas.interview import QAEditRequest, QACorrectionPage  # noqa: E402
from app.schemas.mock_preparation import MockPreparationRequest  # noqa: E402

from app.schemas.transcript_correction import (  # noqa: E402
    TranscriptCorrectionRequest,
    TranscriptCorrectionReceipt,
    TranscriptHistoryPage,
    TranscriptPage,
    TranscriptPlaybackRequest,
)

INPUT_MODELS = (
    TranscriptCorrectionRequest,
    TranscriptPlaybackRequest,
    QAEditRequest,
    MockPreparationRequest,
    ConfirmInterviewInvitation,
    FactConfirmationResolution,
    ResolveInteractionRequest,
    MockClientActionResultRequest,
    MockClientActionTakeoverRequest,
    SubmissionKey,
)
OUTPUT_MODELS = (
    TranscriptCorrectionReceipt,
    TranscriptHistoryPage,
    TranscriptPage,
    QACorrectionPage,
    ConfirmInterviewInvitationResult,
    FactConfirmationRequest,
    InterviewInvitationCandidateFacts,
    InterviewInvitationHandoffView,
    InvitationSubmissionReceipt,
    VerificationView,
    AgentInteractionView,
    PendingInteractionProjection,
    ResolveInteractionResponse,
    MockClientActionRequest,
    MockClientActionView,
    MockClientActionResolutionResponse,
    CareerActivityEvent,
    ContextPackage,
)
SNAPSHOT = ROOT / "frontend/contracts/shared-protocols.openapi.json"


def render_snapshot() -> str:
    models = [(model, "validation") for model in INPUT_MODELS] + [
        (model, "serialization") for model in OUTPUT_MODELS
    ]
    roots, definitions = models_json_schema(
        models, ref_template="#/components/schemas/{model}"
    )
    schemas = definitions["$defs"]
    for model, mode in models:
        name = model.__name__ + (
            "RequestContract" if mode == "validation" else "ResponseContract"
        )
        if name in schemas:
            raise ValueError(f"Duplicate contract alias: {name}")
        schemas[name] = roots[(model, mode)]
    document = {
        "openapi": "3.1.0",
        "info": {"title": "Interview Copilot shared protocols", "version": "1.0.0"},
        "paths": {},
        "components": {"schemas": schemas},
    }
    return json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = render_snapshot()
    if args.check:
        if not SNAPSHOT.is_file() or SNAPSHOT.read_text(encoding="utf-8") != expected:
            print(
                "Shared protocol snapshot is stale; run scripts/export_shared_contracts.py",
                file=sys.stderr,
            )
            return 1
        print("Shared Pydantic protocol snapshot is current")
        return 0
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(expected, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
