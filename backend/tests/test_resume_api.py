"""The published resume route exposes only the caller's exact version spans."""

from fastapi.testclient import TestClient
from app.main import app
from app.core.security import get_current_user
from app.db.database import get_db
from app.career.application.resumes import resume_artifact_service as resumes


def test_sections_api_does_not_expose_another_accounts_resume(db, owners):
    owner, other = owners
    record = resumes.create_resume_artifact(
        db,
        user_pk=owner.id,
        operation_key="route-resume",
        file_asset_id=None,
        title="CV",
        raw_text="我的项目",
        make_default=True,
    )
    record = resumes.persist_extracted_resume(
        db,
        user_pk=owner.id,
        resume_id=record.artifact.id,
        source_version_id=record.current_version.id,
        text="我的项目",
        candidates=resumes.ExtractedProfileCandidates(
            [], [], [{"section_type": "project", "title": "项目", "start": 0, "end": 4}]
        ),
    )
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: owner
    try:
        client = TestClient(app)
        response = client.get(f"/api/v1/resumes/{record.artifact.id}/sections")
        assert response.status_code == 200, response.text
        assert response.json()["artifact_version_id"] == record.current_version.id
        assert response.json()["sections"][0]["section_type"] == "project"
        app.dependency_overrides[get_current_user] = lambda: other
        assert (
            client.get(f"/api/v1/resumes/{record.artifact.id}/sections").status_code
            == 404
        )
    finally:
        app.dependency_overrides.clear()
