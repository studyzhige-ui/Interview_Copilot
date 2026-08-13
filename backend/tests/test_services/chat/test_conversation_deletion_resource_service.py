from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from app.services.chat.conversation_deletion_resource_service import (
    MAX_RECEIPT_RESOURCE_IDENTITIES,
    find_unresolved_conversation_deletion_resource_receipts,
    has_unresolved_conversation_deletion_resource_conflict,
    normalize_receipt_resource_identities,
    receipt_resource_identities_for_call,
)


class _ScalarSession:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows
        self.statement = None

    def scalars(self, statement):  # type: ignore[no-untyped-def]
        self.statement = statement
        return iter(self.rows)


def test_resource_identities_are_canonical_bounded_and_deduplicated() -> None:
    values: list[object] = [
        " artifact:one ",
        "artifact:one",
        "missing-separator",
        ":missing-type",
        "missing-value:",
        3,
        "artifact:" + ("x" * 256),
    ]
    values.extend(f"job:{index}" for index in range(40))

    normalized = normalize_receipt_resource_identities(values)

    assert normalized[0] == "artifact:one"
    assert len(normalized) == MAX_RECEIPT_RESOURCE_IDENTITIES
    assert len(normalized) == len(set(normalized))


def test_receipt_only_copies_unresolved_non_read_resources() -> None:
    identities = ["artifact:one", " artifact:one ", "job:two"]

    assert receipt_resource_identities_for_call(
        SimpleNamespace(
            effect="write",
            status="running",
            resource_identities_json=identities,
        )
    ) == ["artifact:one", "job:two"]
    assert receipt_resource_identities_for_call(
        SimpleNamespace(
            effect="unknown",
            status="unknown",
            resource_identities_json=identities,
        )
    ) == ["artifact:one", "job:two"]
    assert (
        receipt_resource_identities_for_call(
            SimpleNamespace(
                effect="read",
                status="running",
                resource_identities_json=identities,
            )
        )
        == []
    )
    assert (
        receipt_resource_identities_for_call(
            SimpleNamespace(
                effect="write",
                status="completed",
                resource_identities_json=identities,
            )
        )
        == []
    )


def test_same_resource_deleted_receipt_blocks_until_reconciled() -> None:
    receipt = SimpleNamespace(resource_identities_json=["artifact:one", "job:two"])
    unresolved = _ScalarSession([receipt])

    matches = find_unresolved_conversation_deletion_resource_receipts(
        unresolved,  # type: ignore[arg-type]
        user_id=7,
        resource_identities=["artifact:one"],
        lock=True,
        now=datetime(2026, 8, 13, tzinfo=timezone.utc),
    )

    assert matches == [receipt]
    assert unresolved.statement is not None
    assert unresolved.statement._for_update_arg is not None  # noqa: SLF001
    query = str(unresolved.statement)
    assert "user_id" in query
    assert "resolved_at" in query
    assert "retain_until" in query

    reconciled = _ScalarSession([])
    assert not has_unresolved_conversation_deletion_resource_conflict(
        reconciled,  # type: ignore[arg-type]
        user_id=7,
        resource_identities=["artifact:one"],
    )


def test_unrelated_resource_does_not_conflict() -> None:
    db = _ScalarSession(
        [SimpleNamespace(resource_identities_json=["artifact:another"])]
    )

    assert not has_unresolved_conversation_deletion_resource_conflict(
        db,  # type: ignore[arg-type]
        user_id=7,
        resource_identities=["artifact:one"],
    )
