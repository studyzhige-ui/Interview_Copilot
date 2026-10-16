"""The growth summary uses the same topics as current interview projections."""

from app.core.scoring import SCORE_SCALE_VERSION
from app.observability.diagnostics_report_service import _build_report


def test_current_interview_signal_types_produce_scored_topics_without_duplicates():
    records = [
        {
            "topic": "沟通表达",
            "signal_type": "interview_performance",
            "score": 8,
            "time": "2030-01-01",
            "summary": "Earlier evidence",
            "evidence_count": 1,
        },
        {
            "topic": "沟通表达",
            "signal_type": "mock_interview_performance",
            "score": 8,
            "time": "2030-02-01",
            "summary": "Latest evidence",
            "evidence_count": 1,
        },
        {
            "topic": "系统设计",
            "signal_type": "mock_interview_performance",
            "score": 5,
            "time": "2030-02-01",
            "summary": "Design evidence",
            "evidence_count": 1,
        },
    ]
    for record in records:
        record["score_version"] = SCORE_SCALE_VERSION
    report = _build_report(records, scale_version=SCORE_SCALE_VERSION)
    assert report["overall"] == 6.5
    assert {axis["k"]: axis["v"] for axis in report["axes"]} == {
        "沟通表达": 8,
        "系统设计": 5,
    }
    assert report["totals"]["scored_topics"] == 2
    assert report["totals"]["assessment_count"] == 3
    assert len(report["strengths"]) == 1
    assert report["strengths"][0]["evidence"] == "Latest evidence"
    assert [row["topic"] for row in report["weaknesses"]] == ["系统设计"]


def test_unscored_topics_stay_unknown_and_real_zero_is_counted():
    report = _build_report(
        [
            {"topic": "Unscored", "score": None, "summary": "Qualitative only"},
            {
                "topic": "Assessed",
                "score": 0,
                "score_version": SCORE_SCALE_VERSION,
                "summary": "Scored evidence",
            },
        ],
        scale_version=SCORE_SCALE_VERSION,
    )
    assert {axis["k"]: axis["v"] for axis in report["axes"]} == {
        "Unscored": None,
        "Assessed": 0,
    }
    assert report["overall"] == 0
    assert report["totals"]["scored_topics"] == 1
