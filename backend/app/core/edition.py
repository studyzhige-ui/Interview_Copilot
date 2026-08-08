from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class AppEdition(StrEnum):
    CLOUD = "cloud"
    COMMUNITY = "community"


@dataclass(frozen=True)
class EditionPolicy:
    edition: AppEdition
    display_name: str
    managed_ai_roles: tuple[str, ...]
    supported_mcp_transports: tuple[str, ...]
    allow_provider_connection_overrides: bool
    show_advanced_model_settings: bool
    expose_rag_diagnostics: bool

    def validate_provider_patch(self, patch: dict[str, Any]) -> None:
        if self.allow_provider_connection_overrides:
            return
        advanced = ("api_base_override", "organization_id", "extra_headers_json")
        if any(patch.get(field) not in (None, "") for field in advanced):
            raise ValueError(
                "Cloud edition only supports official provider endpoints; "
                "custom connection settings are available in Community edition"
            )

    def public_payload(self, *, stdio_enabled: bool) -> dict[str, Any]:
        transports = [
            transport
            for transport in self.supported_mcp_transports
            if transport != "stdio" or stdio_enabled
        ]
        return {
            "edition": self.edition.value,
            "display_name": self.display_name,
            "managed_ai_roles": list(self.managed_ai_roles),
            "mcp_transports": transports,
            "allow_provider_connection_overrides": self.allow_provider_connection_overrides,
            "show_advanced_model_settings": self.show_advanced_model_settings,
            "expose_rag_diagnostics": self.expose_rag_diagnostics,
        }


_POLICIES = {
    AppEdition.CLOUD: EditionPolicy(
        edition=AppEdition.CLOUD,
        display_name="Interview Copilot Cloud",
        managed_ai_roles=("embedding", "reranker", "transcription", "diarization"),
        supported_mcp_transports=("streamable_http",),
        allow_provider_connection_overrides=False,
        show_advanced_model_settings=False,
        expose_rag_diagnostics=False,
    ),
    AppEdition.COMMUNITY: EditionPolicy(
        edition=AppEdition.COMMUNITY,
        display_name="Interview Copilot Community",
        managed_ai_roles=(),
        supported_mcp_transports=("streamable_http", "stdio"),
        allow_provider_connection_overrides=True,
        show_advanced_model_settings=True,
        expose_rag_diagnostics=True,
    ),
}


def policy_for(edition: str | AppEdition) -> EditionPolicy:
    return _POLICIES[AppEdition(edition)]


def current_edition_policy() -> EditionPolicy:
    from app.core.config import settings

    return policy_for(settings.APP_EDITION)


__all__ = [
    "AppEdition",
    "EditionPolicy",
    "current_edition_policy",
    "policy_for",
]
