"""Resume versions, semantic spans, candidate approval and stale-worker fencing."""

import json
from types import SimpleNamespace

import pytest
from app.career.application.resumes import resume_artifact_service as resumes
from app.career.application import artifacts
from app.schemas.artifact import ArtifactWriteInput

TEXT = "项目经历\n检索系统：负责 Python 开发\n教育经历\n计算机硕士"
SECTIONS = [
    {"section_type": "project", "title": "检索系统", "start_line": 1, "end_line": 2},
    {"section_type": "education", "title": "教育经历", "start_line": 3, "end_line": 4},
]


@pytest.mark.asyncio
async def test_extraction_preserves_every_character_and_uses_one_model_call(
    monkeypatch,
):
    calls = []

    async def complete(prompt, **kwargs):
        calls.append(prompt)
        return SimpleNamespace(
            text=json.dumps({"facts": [], "directions": [], "sections": SECTIONS})
        )

    monkeypatch.setattr(
        resumes, "get_internal_llm", lambda _: SimpleNamespace(acomplete=complete)
    )
    result = await resumes.extract_profile_candidates(TEXT)
    assert len(calls) == 1 and "4: 计算机硕士" in calls[0]
    assert "".join(TEXT[s["start"] : s["end"]] for s in result.sections) == TEXT
    assert [s["section_type"] for s in result.sections] == ["project", "education"]


@pytest.mark.parametrize(
    "rows",
    [
        [],
        None,
        SECTIONS[:1],
        [SECTIONS[1], SECTIONS[0]],
        [{**SECTIONS[0], "end_line": 5}],
        [{**SECTIONS[0], "start_line": True}],
        [{**SECTIONS[0], "section_type": "invented"}],
        [{**SECTIONS[0], "content": "rewritten"}],
    ],
)
def test_missing_overlapping_or_rewritten_sections_cannot_be_published(rows):
    with pytest.raises(resumes.ResumeArtifactError):
        resumes._section_spans(TEXT, rows)


def test_versioned_sections_do_not_create_a_second_resume_owner(db, owners):
    owner, other = owners
    record = resumes.create_resume_artifact(
        db,
        file_asset_id=None,
        make_default=None,
        user_pk=owner.id,
        operation_key="import-resume",
        title="CV",
        raw_text=TEXT,
    )
    repeated = resumes.create_resume_artifact(
        db,
        file_asset_id=None,
        make_default=None,
        user_pk=owner.id,
        operation_key="import-resume",
        title="CV",
        raw_text=TEXT,
    )
    assert repeated.artifact.id == record.artifact.id
    with pytest.raises(resumes.ResumeArtifactNotFoundError):
        resumes.resolve_owned_resume(db, user_pk=other.id, resume_id=record.artifact.id)
    source_id = record.current_version.id
    record = resumes.persist_extracted_resume(
        db,
        user_pk=owner.id,
        resume_id=record.artifact.id,
        source_version_id=source_id,
        text=TEXT,
        candidates=resumes.ExtractedProfileCandidates(
            [], [], resumes._section_spans(TEXT, SECTIONS)
        ),
    )
    assert len(resumes.read_resume_sections(record)) == 2
    assert "content" not in json.loads(record.state.section_spans_json)[0]
    artifacts.edit_artifact(
        db,
        user_pk=owner.id,
        artifact_id=record.artifact.id,
        operation_key="edit",
        version=ArtifactWriteInput(
            title="CV", content_text="新版本", content_format="plain_text"
        ),
    )
    current = resumes.resolve_owned_resume(
        db, user_pk=owner.id, resume_id=record.artifact.id
    )
    assert resumes.read_resume_sections(current) == []
    with pytest.raises(resumes.ResumeArtifactStaleVersionError):
        resumes.persist_extracted_resume(
            db,
            user_pk=owner.id,
            resume_id=record.artifact.id,
            source_version_id=source_id,
            text=TEXT,
            candidates=resumes.ExtractedProfileCandidates([], [], []),
        )


def test_resume_archive_and_default_are_owned_commands(db, owners):
    owner, _ = owners
    first = resumes.create_resume_artifact(
        db,
        file_asset_id=None,
        make_default=None,
        user_pk=owner.id,
        operation_key="first",
        title="A",
        raw_text="A",
    )
    second = resumes.create_resume_artifact(
        db,
        file_asset_id=None,
        make_default=None,
        user_pk=owner.id,
        operation_key="second",
        title="B",
        raw_text="B",
    )
    resumes.set_default_resume_artifact(
        db, user_pk=owner.id, resume_id=second.artifact.id
    )
    resumes.archive_resume_artifact(db, user_pk=owner.id, resume_id=second.artifact.id)
    remaining = resumes.list_resume_artifacts(db, user_pk=owner.id)
    assert (
        len(remaining) == 1
        and remaining[0].artifact.id == first.artifact.id
        and remaining[0].state.is_default
    )
