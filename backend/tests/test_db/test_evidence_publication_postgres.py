"""Source publication fences must refresh identities across real DB sessions."""

import pytest

from app.models.file_asset import FileAsset
from app.models.interview_record import InterviewRecord
from app.models.interview_transcript import InterviewTranscript
from tests.test_services.interview.test_evidence_publication import publish, seed_source


def test_cached_source_cannot_hide_a_committed_version_change(database):
    _, _, factory = database
    with factory() as setup:
        record, asset, evidence = seed_source(setup)
        setup.commit()
        record_id, asset_id = record.id, asset.id
    with factory() as worker:
        cached = worker.get(FileAsset, asset_id)
        worker.commit()  # factory intentionally uses expire_on_commit=False
        with factory() as editor:
            editor.get(FileAsset, asset_id).checksum_sha256 = "1" * 64
            editor.commit()
        assert cached.checksum_sha256 == "0" * 64
        with pytest.raises(ValueError, match="source_superseded"):
            publish(worker, worker.get(InterviewRecord, record_id), evidence)
        worker.rollback()
    with factory() as verify:
        assert verify.query(InterviewTranscript).count() == 0
        assert verify.get(InterviewRecord, record_id).transcript_id is None
