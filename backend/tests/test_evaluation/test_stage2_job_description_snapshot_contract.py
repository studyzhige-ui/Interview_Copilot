from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_snapshot_is_opportunity_owned_append_only_state() -> None:
    model = _read("backend/app/models/job_description_snapshot.py")
    migration = _read("alembic/versions/0039_job_description_snapshots.py")

    assert 'ForeignKey("job_opportunities.id", ondelete="CASCADE")' in model
    assert "before_update" in model
    assert "before_delete" in model
    assert 'revision = "0039"' in migration
    assert 'down_revision = "0038"' in migration


def test_snapshot_intake_has_concrete_owned_sources_only() -> None:
    service = _read("backend/app/services/job_description_snapshot_service.py")

    assert '{"read_url", "search_jobs"}' in service
    assert 'AgentToolCall.status == "completed"' in service
    assert "AgentToolCall.user_id == user_pk" in service
    assert "AgentToolCall.session_id == command.tool_session_id" in service
    assert "JobDescriptionSnapshotFromProductUI" in service
    assert "SourceRegistry" not in service
    assert "Evidence" not in service


def test_application_event_freezes_snapshot_at_event_time() -> None:
    service = _read("backend/app/services/career_process_service.py")

    assert "at_or_before=command.occurred_at" in service
    assert (
        "jd_snapshot_id=jd_snapshot.id if jd_snapshot is not None else None" in service
    )
    assert (
        "jd_snapshot_version=jd_snapshot.version if jd_snapshot is not None else None"
        in service
    )
    assert "jd_snapshot_id=target.jd_snapshot_id" in service
    assert "jd_snapshot_version=target.jd_snapshot_version" in service


def test_analysis_context_verifies_the_frozen_database_row() -> None:
    service = _read("backend/app/services/career_process_service.py")

    assert "JobDescriptionSnapshot.id == snapshot_id" in service
    assert "JobDescriptionSnapshot.version == snapshot_version" in service
    assert "JobDescriptionSnapshot.job_opportunity_id == opportunity_id" in service
    assert '"jd_snapshot_identity": None' not in service


def test_public_api_accepts_only_explicit_typed_product_ui_intake() -> None:
    api = _read("backend/app/api/career_process.py")

    assert '"/opportunities/{opportunity_id}/jd-snapshots"' in api
    assert "command: JobDescriptionSnapshotFromProductUI" in api
    assert "JobDescriptionSnapshotFromToolResult" not in api
