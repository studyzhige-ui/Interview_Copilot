from types import SimpleNamespace

from app.services.chat.attachment_coverage import (
    attachment_execution_requirements,
    attachment_requirement_block_reason,
)


def test_requirements_only_include_unproven_runtime_work():
    requirements = attachment_execution_requirements(
        [
            {
                "attachment_ref_id": "ref-short",
                "title": "short",
                "coverage": {"requires_segmented_read": False},
                "content_capabilities": {"visual_layout_requested": False},
            },
            {
                "source_ref_id": "ref-long",
                "title": "long",
                "coverage": {"requires_segmented_read": True},
                "content_capabilities": {"visual_layout_requested": False},
            },
            {
                "attachment_ref_id": "ref-layout",
                "title": "layout",
                "coverage": {"requires_segmented_read": False},
                "content_capabilities": {
                    "visual_layout_requested": True,
                    "visual_layout_reviewed": False,
                    "visual_layout_scope": {
                        "full_document": False,
                        "required_page_start": 2,
                        "required_page_end": 3,
                        "scope_source": "explicit_page_interval",
                    },
                },
            },
        ]
    )

    assert requirements == (
        {
            "kind": "full_text_read",
            "identity_kind": "source_ref",
            "identity": "ref-long",
            "title": "long",
        },
        {
            "kind": "visual_layout_unavailable",
            "identity_kind": "attachment_ref",
            "identity": "ref-layout",
            "full_document": False,
            "required_page_start": 2,
            "required_page_end": 3,
            "scope_source": "explicit_page_interval",
            "title": "layout",
        },
    )


def test_full_read_requires_contiguous_persisted_coverage():
    requirement = (
        {
            "kind": "full_text_read",
            "identity_kind": "attachment_ref",
            "identity": "ref-1",
            "title": "long",
        },
    )
    first = SimpleNamespace(
        tool_name="read_file",
        status="completed",
        arguments_json={"attachment_ref_id": "ref-1", "offset": 0},
        result_json={
            "coverage": {
                "segment_start": 0,
                "segment_end": 50,
                "total_chars": 100,
            }
        },
    )
    tail = SimpleNamespace(
        tool_name="read_file",
        status="completed",
        arguments_json={"attachment_ref_id": "ref-1", "offset": 50},
        result_json={
            "coverage": {
                "segment_start": 50,
                "segment_end": 100,
                "total_chars": 100,
            }
        },
    )

    assert attachment_requirement_block_reason(requirement, [first]) == (
        "attachment_full_coverage_incomplete:ref-1"
    )
    assert attachment_requirement_block_reason(requirement, [tail]) == (
        "attachment_full_coverage_incomplete:ref-1"
    )
    assert attachment_requirement_block_reason(requirement, [first, tail]) is None


def test_visual_layout_without_receipt_is_always_blocked():
    reason = attachment_requirement_block_reason(
        (
            {
                "kind": "visual_layout_unavailable",
                "identity_kind": "attachment_ref",
                "identity": "ref-layout",
                "title": "layout",
            },
        ),
        [],
    )
    assert reason == "attachment_visual_layout_unavailable:ref-layout"


def _visual_call(
    *,
    start: int,
    end: int,
    total: int,
    version: str = "sha256:v1",
):
    count = end - start + 1
    return SimpleNamespace(
        tool_name="inspect_attachment_pages",
        status="completed",
        arguments_json={"attachment_ref_id": "ref-layout"},
        result_json={
            "status": "completed",
            "identity_kind": "attachment_ref",
            "identity": "ref-layout",
            "file_asset_id": "fa-layout",
            "file_asset_version": version,
            "coverage": {
                "type": "page_visual_inspection",
                "page_start": start,
                "page_end": end,
                "total_pages": total,
                "rendered_page_count": count,
            },
            "receipt": {
                "type": "model_page_vision",
                "status": "completed",
                "identity_kind": "attachment_ref",
                "identity": "ref-layout",
                "file_asset_id": "fa-layout",
                "file_asset_version": version,
                "page_start": start,
                "page_end": end,
                "total_pages": total,
                "rendered_page_count": count,
                "rendered_page_sha256": ["a" * 64] * count,
                "model_profile_id": "openai/vision",
                "provider": "openai",
                "model": "vision",
                "provider_response_sha256": "b" * 64,
            },
        },
    )


def test_visual_layout_requires_contiguous_exact_version_receipts():
    requirement = (
        {
            "kind": "visual_layout_unavailable",
            "identity_kind": "attachment_ref",
            "identity": "ref-layout",
            "file_asset_id": "fa-layout",
            "file_asset_version": "sha256:v1",
            "full_document": True,
            "required_page_start": 1,
            "scope_source": "explicit_full_document_visual_request",
            "title": "layout.pdf",
        },
    )
    first = _visual_call(start=1, end=2, total=4)
    tail = _visual_call(start=3, end=4, total=4)

    assert attachment_requirement_block_reason(requirement, [first]) == (
        "attachment_visual_layout_unavailable:ref-layout"
    )
    assert attachment_requirement_block_reason(requirement, [first, tail]) is None
    assert (
        attachment_requirement_block_reason(
            requirement,
            [first, _visual_call(start=3, end=4, total=4, version="sha256:other")],
        )
        == "attachment_visual_layout_unavailable:ref-layout"
    )


def test_visual_layout_rejects_claim_without_real_receipt_metadata():
    requirement = (
        {
            "kind": "visual_layout_unavailable",
            "identity_kind": "attachment_ref",
            "identity": "ref-layout",
            "full_document": False,
            "required_page_start": 1,
            "required_page_end": 1,
            "title": "layout.pdf",
        },
    )
    forged = _visual_call(start=1, end=1, total=1)
    forged.result_json["receipt"].pop("provider_response_sha256")

    assert attachment_requirement_block_reason(requirement, [forged]) == (
        "attachment_visual_layout_unavailable:ref-layout"
    )


def test_local_visual_page_interval_needs_only_that_exact_interval():
    requirement = (
        {
            "kind": "visual_layout_unavailable",
            "identity_kind": "attachment_ref",
            "identity": "ref-layout",
            "file_asset_id": "fa-layout",
            "file_asset_version": "sha256:v1",
            "full_document": False,
            "required_page_start": 2,
            "required_page_end": 3,
            "scope_source": "explicit_page_interval",
            "title": "layout.pdf",
        },
    )

    assert (
        attachment_requirement_block_reason(
            requirement,
            [_visual_call(start=2, end=3, total=12)],
        )
        is None
    )
    assert (
        attachment_requirement_block_reason(
            requirement,
            [_visual_call(start=1, end=1, total=12)],
        )
        == "attachment_visual_layout_unavailable:ref-layout"
    )


def test_bounded_visual_request_does_not_require_whole_document():
    requirement = (
        {
            "kind": "visual_layout_unavailable",
            "identity_kind": "attachment_ref",
            "identity": "ref-layout",
            "full_document": False,
            "required_page_start": 1,
            "required_page_end": 1,
            "scope_source": "bounded_default_page",
            "title": "layout.pdf",
        },
    )

    assert (
        attachment_requirement_block_reason(
            requirement,
            [_visual_call(start=1, end=1, total=20)],
        )
        is None
    )
