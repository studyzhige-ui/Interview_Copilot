"""Single source of truth for upload purposes (UP-5).

Before this module, the per-purpose rules were split across two drifting
vocabularies: ``app/api/file_assets._PURPOSE_LIMITS`` (presigned flow,
resume=20MB) and ``app/services/uploads/file_validation._SIZE_LIMITS_BYTES``
(direct ephemeral endpoints, resume=10MB). Every consumer now reads from
here:

* ``file_asset_service.create_file_asset`` — purpose whitelist, declared-size
  cap, presigned-URL TTL
* ``file_asset_service`` confirm/consume verification — actual-size cap +
  magic-byte content kind
* ``file_validation`` — size caps for the direct (non-persisted) endpoints

Change a number here and every path moves together.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# What the first bytes of an upload must look like, checked at
# confirm/consume via a 32-byte head read (file_validation.detect_head_format):
#   audio     — recognised audio/video container magic
#   document  — pdf / docx-zip / txt-md text (the strict resume/JD family)
#   knowledge — anything the knowledge whitelist can parse: pdf / OOXML zip /
#               legacy-Office OLE / image / text-family (extension gate runs
#               separately at POST /knowledge/documents)
#   image     — png / jpeg / gif / webp
#   text      — non-binary head
ContentKind = Literal["audio", "document", "knowledge", "image", "text"]

_MB = 1024 * 1024

# Presigned PUT TTLs (UP-7). The URL only needs to outlive the client's
# upload. 10 minutes is plenty for documents/clips; only full interview
# recordings (up to 500 MB on a slow uplink) get the long window. A shorter
# TTL narrows the confirm-time TOCTOU: after confirm the URL can still be
# replayed until expiry, so the replay window is now minutes, not an hour.
_TTL_SHORT = 600
_TTL_AUDIO = 3600


@dataclass(frozen=True)
class PurposeSpec:
    key: str
    max_bytes: int
    content_kind: ContentKind
    presign_ttl_seconds: int


PURPOSE_REGISTRY: dict[str, PurposeSpec] = {
    spec.key: spec
    for spec in (
        PurposeSpec("resume", 20 * _MB, "document", _TTL_SHORT),
        PurposeSpec("jd", 10 * _MB, "document", _TTL_SHORT),
        PurposeSpec("knowledge_document", 50 * _MB, "knowledge", _TTL_SHORT),
        PurposeSpec("interview_audio", 500 * _MB, "audio", _TTL_AUDIO),
        PurposeSpec("mock_audio_clip", 25 * _MB, "audio", _TTL_SHORT),
        # Matches the /me/avatar set-time cap so a too-large image is rejected
        # at upload-url time rather than after a wasted PUT.
        PurposeSpec("avatar", 1 * _MB, "image", _TTL_SHORT),
        # Server-written agent exports (write_file tool) — never client bytes.
        PurposeSpec("agent_output", 20 * _MB, "text", _TTL_SHORT),
    )
}


def get_purpose_spec(purpose: str) -> PurposeSpec | None:
    return PURPOSE_REGISTRY.get(purpose)


__all__ = ["ContentKind", "PurposeSpec", "PURPOSE_REGISTRY", "get_purpose_spec"]
