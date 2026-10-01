"""Runtime-only checks for explicit attachment coverage claims.

This module does not own files, scopes, or a second execution state.  It turns
the current Source Resolver projection into deterministic completion checks so
"full review" cannot be satisfied by a top-k sample or by model prose.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any


def attachment_execution_requirements(
    documents: Sequence[dict[str, Any]],
) -> tuple[dict[str, Any], ...]:
    """Return only constraints that need work beyond injected context."""

    requirements: list[dict[str, Any]] = []
    for document in documents:
        identity_kind, identity = _document_identity(document)
        if not identity:
            continue
        capabilities = document.get("content_capabilities")
        capabilities = capabilities if isinstance(capabilities, dict) else {}
        coverage = document.get("coverage")
        coverage = coverage if isinstance(coverage, dict) else {}
        if bool(capabilities.get("visual_layout_requested")) and not bool(
            capabilities.get("visual_layout_reviewed")
        ):
            visual_scope = capabilities.get("visual_layout_scope")
            visual_scope = visual_scope if isinstance(visual_scope, dict) else {}
            requirements.append(
                {
                    "kind": "visual_layout_unavailable",
                    "identity_kind": identity_kind,
                    "identity": identity,
                    **_version_fields(document),
                    **_visual_scope_fields(visual_scope),
                    "title": str(document.get("title") or identity),
                }
            )
        if bool(coverage.get("requires_segmented_read")):
            requirements.append(
                {
                    "kind": "full_text_read",
                    "identity_kind": identity_kind,
                    "identity": identity,
                    **_version_fields(document),
                    "title": str(document.get("title") or identity),
                }
            )
    return tuple(requirements)


def attachment_requirement_block_reason(
    requirements: Sequence[dict[str, Any]],
    tool_calls: Iterable[object],
) -> str | None:
    """Return a stable reason while a current attachment claim is unproven."""

    calls = tuple(tool_calls)
    for requirement in requirements:
        kind = requirement.get("kind")
        identity = requirement.get("identity") or "unknown"
        if kind == "visual_layout_unavailable" and not _visual_read_proven(
            requirement,
            calls,
        ):
            return f"attachment_visual_layout_unavailable:{identity}"
        if kind == "full_text_read" and not _full_read_proven(
            requirement,
            calls,
        ):
            return f"attachment_full_coverage_incomplete:{identity}"
    return None


def _full_read_proven(
    requirement: dict[str, Any],
    tool_calls: Iterable[object],
) -> bool:
    identity_kind = requirement.get("identity_kind")
    identity = requirement.get("identity")
    argument_key = (
        "attachment_ref_id" if identity_kind == "attachment_ref" else "source_ref_id"
    )
    intervals: list[tuple[int, int, int]] = []
    for call in tool_calls:
        if (
            str(getattr(call, "tool_name", "")) != "read_file"
            or str(getattr(call, "status", "")) != "completed"
        ):
            continue
        arguments = getattr(call, "arguments_json", None)
        result = getattr(call, "result_json", None)
        if not isinstance(arguments, dict) or not isinstance(result, dict):
            continue
        if str(arguments.get(argument_key) or "") != identity or result.get("error"):
            continue
        if not _result_version_matches(requirement, result):
            continue
        coverage = result.get("coverage")
        if not isinstance(coverage, dict):
            continue
        try:
            start = int(coverage["segment_start"])
            end = int(coverage["segment_end"])
            total = int(coverage["total_chars"])
        except (KeyError, TypeError, ValueError):
            continue
        if total > 0 and 0 <= start < end <= total:
            intervals.append((start, end, total))
    if not intervals:
        return False
    totals = {total for _, _, total in intervals}
    if len(totals) != 1:
        return False
    total = totals.pop()
    cursor = 0
    for start, end, _ in sorted(intervals):
        if start > cursor:
            return False
        cursor = max(cursor, end)
        if cursor >= total:
            return True
    return False


def _visual_read_proven(
    requirement: dict[str, Any],
    tool_calls: Iterable[object],
) -> bool:
    identity_kind = requirement.get("identity_kind")
    identity = requirement.get("identity")
    argument_key = (
        "attachment_ref_id" if identity_kind == "attachment_ref" else "source_ref_id"
    )
    intervals: list[tuple[int, int, int]] = []
    for call in tool_calls:
        if (
            str(getattr(call, "tool_name", "")) != "inspect_attachment_pages"
            or str(getattr(call, "status", "")) != "completed"
        ):
            continue
        arguments = getattr(call, "arguments_json", None)
        result = getattr(call, "result_json", None)
        if not isinstance(arguments, dict) or not isinstance(result, dict):
            continue
        if str(arguments.get(argument_key) or "") != identity or result.get("error"):
            continue
        if result.get("status") != "completed" or not _result_version_matches(
            requirement,
            result,
        ):
            continue
        if (
            result.get("identity_kind") != identity_kind
            or str(result.get("identity") or "") != identity
        ):
            continue
        coverage = result.get("coverage")
        receipt = result.get("receipt")
        if not isinstance(coverage, dict) or not isinstance(receipt, dict):
            continue
        if (
            coverage.get("type") != "page_visual_inspection"
            or receipt.get("type") != "model_page_vision"
            or receipt.get("status") != "completed"
            or receipt.get("identity_kind") != identity_kind
            or str(receipt.get("identity") or "") != identity
            or str(receipt.get("file_asset_id") or "")
            != str(result.get("file_asset_id") or "")
            or str(receipt.get("file_asset_version") or "")
            != str(result.get("file_asset_version") or "")
            or not str(receipt.get("model_profile_id") or "")
            or not str(receipt.get("provider") or "")
            or not str(receipt.get("model") or "")
            or not _is_sha256(receipt.get("provider_response_sha256"))
        ):
            continue
        try:
            start = int(coverage["page_start"])
            end = int(coverage["page_end"])
            total = int(coverage["total_pages"])
            rendered_count = int(coverage["rendered_page_count"])
            receipt_start = int(receipt["page_start"])
            receipt_end = int(receipt["page_end"])
            receipt_total = int(receipt["total_pages"])
            receipt_count = int(receipt["rendered_page_count"])
        except (KeyError, TypeError, ValueError):
            continue
        page_hashes = receipt.get("rendered_page_sha256")
        if (
            not (1 <= start <= end <= total)
            or rendered_count != end - start + 1
            or (receipt_start, receipt_end, receipt_total) != (start, end, total)
            or receipt_count != rendered_count
            or not isinstance(page_hashes, list)
            or len(page_hashes) != rendered_count
            or any(not _is_sha256(value) for value in page_hashes)
        ):
            continue
        intervals.append((start, end, total))
    if not intervals:
        return False
    full_document = bool(requirement.get("full_document"))
    required_start = int(requirement.get("required_page_start") or 1)
    required_end_raw = requirement.get("required_page_end")
    totals = {total for _, _, total in intervals}
    if len(totals) != 1:
        return False
    total = totals.pop()
    required_end = total if full_document else int(required_end_raw or required_start)
    if required_start > total or required_end > total:
        return False
    cursor = required_start - 1
    for start, end, _ in sorted(intervals):
        if end < required_start or start > required_end:
            continue
        clipped_start = max(start, required_start)
        clipped_end = min(end, required_end)
        if clipped_start > cursor + 1:
            return False
        cursor = max(cursor, clipped_end)
        if cursor >= required_end:
            return True
    return False


def _result_version_matches(
    requirement: dict[str, Any],
    result: dict[str, Any],
) -> bool:
    expected_asset = requirement.get("file_asset_id")
    expected_version = requirement.get("file_asset_version")
    if expected_asset and str(result.get("file_asset_id") or "") != expected_asset:
        return False
    return not expected_version or (
        str(result.get("file_asset_version") or "") == expected_version
    )


def _is_sha256(value: Any) -> bool:
    normalized = str(value or "").casefold()
    return len(normalized) == 64 and all(
        character in "0123456789abcdef" for character in normalized
    )


def _document_identity(document: dict[str, Any]) -> tuple[str, str]:
    attachment_ref_id = str(document.get("attachment_ref_id") or "").strip()
    if attachment_ref_id:
        return "attachment_ref", attachment_ref_id
    return "source_ref", str(document.get("source_ref_id") or "").strip()


def _version_fields(document: dict[str, Any]) -> dict[str, str]:
    fields: dict[str, str] = {}
    file_asset_id = str(document.get("file_asset_id") or "").strip()
    file_asset_version = str(document.get("file_asset_version") or "").strip()
    if file_asset_id:
        fields["file_asset_id"] = file_asset_id
    if file_asset_version:
        fields["file_asset_version"] = file_asset_version
    return fields


def _visual_scope_fields(scope: dict[str, Any]) -> dict[str, Any]:
    full_document = bool(scope.get("full_document"))
    try:
        page_start = max(1, int(scope.get("required_page_start") or 1))
    except (TypeError, ValueError):
        page_start = 1
    fields: dict[str, Any] = {
        "full_document": full_document,
        "required_page_start": 1 if full_document else page_start,
        "scope_source": str(scope.get("scope_source") or "bounded_default_page"),
    }
    if not full_document:
        try:
            page_end = max(
                page_start, int(scope.get("required_page_end") or page_start)
            )
        except (TypeError, ValueError):
            page_end = page_start
        fields["required_page_end"] = page_end
    warning = str(scope.get("scope_warning") or "").strip()
    if warning:
        fields["scope_warning"] = warning
    return fields


__all__ = [
    "attachment_execution_requirements",
    "attachment_requirement_block_reason",
]
