"""Operator diagnostics use current owners and distinguish failure from clean data."""

import pytest

from scripts import consistency_scan as scan
from app.career.application import artifacts
from app.models.chat import Conversation
from app.models.file_asset import FileAsset
from app.models.interview_record import InterviewRecord
from app.schemas.artifact import ArtifactWriteInput


def test_resume_file_referenced_by_archived_artifact_is_not_orphaned(db, owners):
    owner, _ = owners
    assets = [
        FileAsset(
            user_id=owner.id,
            purpose="resume",
            original_filename=name,
            object_key=name,
            storage_uri="local://" + name,
            upload_status="uploaded",
            validation_status="passed",
        )
        for name in ("retained.pdf", "unreferenced.pdf")
    ]
    db.add_all(assets)
    db.flush()
    artifact = artifacts.save_artifact_explicitly(
        db,
        user_pk=owner.id,
        operation_key="test-resume",
        artifact_kind="resume",
        version=ArtifactWriteInput(title="CV", file_asset_id=assets[0].id),
    )
    artifacts.archive_artifact(db, user_pk=owner.id, artifact_id=artifact.id)
    finding = scan.scan_orphan_file_assets(db)[0]
    assert finding.count == 1 and finding.sample_ids == [assets[1].id]


def test_agent_mode_does_not_require_subject_but_interview_type_requires_owner(
    db, owners
):
    owner, other = owners
    record = InterviewRecord(user_id=owner.id, source="mock")
    db.add(record)
    db.flush()
    general = Conversation(user_id=owner.id, type="general", mode="agent")
    automation = Conversation(user_id=owner.id, type="persistent_task", mode="agent")
    valid = Conversation(
        user_id=owner.id,
        type="debrief",
        mode="chat",
        subject_type="interview_record",
        subject_id=record.id,
    )
    missing = Conversation(user_id=owner.id, type="mock_interview", mode="chat")
    foreign = Conversation(
        user_id=other.id,
        type="debrief",
        mode="chat",
        subject_type="interview_record",
        subject_id=record.id,
    )
    db.add_all([general, automation, valid, missing, foreign])
    db.flush()
    finding = scan.scan_subjectless_conversations(db)[0]
    assert finding.count == 2 and set(finding.sample_ids) == {missing.id, foreign.id}


@pytest.mark.parametrize("count, code", [(0, 0), (1, 1), (-1, 2)])
def test_scan_exit_code_distinguishes_clean_findings_and_failed_checks(
    monkeypatch, count, code
):
    monkeypatch.setattr(scan, "run_scan", lambda: [scan.Finding("check", count)])
    assert scan.main() == code
