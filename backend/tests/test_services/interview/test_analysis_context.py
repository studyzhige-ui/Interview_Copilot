from types import SimpleNamespace

from app.services.interview.analysis_context import build_analysis_context


def test_analysis_context_uses_report_summary_and_compact_question_index():
    analysis = {
        "overall": {
            "score": 5.0,
            "summary": "整体叙述作为复盘上下文的中心段落。",
            "strengths": ["能说明基本思路"],
            "weaknesses": ["边界条件不足"],
            "key_growth_areas": [
                {"area": "异常处理", "next_step": "一周内补充三个失败案例"}
            ],
        },
        "phase_summary": [
            {
                "phase": "technical",
                "phase_name": "技术基础",
                "score": 5.0,
                "question_count": 2,
                "summary": "一题错误，一题准确。",
            }
        ],
        "skill_radar": {"基础知识": 0.0, "系统设计": None},
    }
    qa_rows = [
        SimpleNamespace(
            order_idx=0, question="问题一", answer="不应进入上下文", score=0.0
        ),
        SimpleNamespace(
            order_idx=1, question="问题二", answer="也不应进入上下文", score=None
        ),
    ]

    context = build_analysis_context(analysis, qa_rows)

    assert "整体叙述作为复盘上下文的中心段落" in context
    assert "异常处理：一周内补充三个失败案例" in context
    assert "技术基础 · 5/10" in context
    assert "基础知识: 0/10" in context
    assert "系统设计: 未考察" in context
    assert "Q1 · 0/10: 问题一" in context
    assert "Q2 · 未评分: 问题二" in context
    assert "不应进入上下文" not in context
    assert "也不应进入上下文" not in context
