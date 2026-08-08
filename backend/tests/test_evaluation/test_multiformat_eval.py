from __future__ import annotations

from pathlib import Path

from evaluation.multiformat_eval import QUESTIONS, render_fixtures


def test_multiformat_equivalence_suite_covers_supported_format_families(tmp_path: Path):
    rendered = render_fixtures(tmp_path)
    extensions = {case.extension for case, _path in rendered}

    assert {".txt", ".md", ".html", ".json", ".csv", ".py"} <= extensions
    assert {".docx", ".pptx", ".xlsx", ".pdf", ".png"} <= extensions
    assert len(QUESTIONS) >= 3
    assert all(path.is_file() and path.stat().st_size > 0 for _case, path in rendered)
