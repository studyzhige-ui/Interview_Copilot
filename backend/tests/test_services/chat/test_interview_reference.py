import json

from app.services.chat.interview_reference import (
    InterviewQuestionReference,
    InterviewReference,
    render_interview_reference,
)


def _question(index: int) -> InterviewQuestionReference:
    return InterviewQuestionReference(
        order_idx=index - 1,
        phase="technical",
        question=f"问题 {index}",
        answer=f"回答 {index}",
        score=float(index),
        critique=f"点评 {index}",
        improved_answer=f"优化回答 {index}",
        tags=(f"知识点 {index}",),
    )


def test_reference_renders_all_selected_questions_in_requested_order():
    reference = InterviewReference(
        record_id="record-1",
        title="后端面试",
        tag="Python",
        source="mock",
        status="completed",
        analysis_json=json.dumps({"overall": {"score": 7, "summary": "整体总结"}}),
        resume_text="很长的简历正文",
        audio_file_asset_id=None,
        resume_id=None,
        resume_file_asset_id=None,
        jd_file_asset_id=None,
        questions=(_question(2), _question(5), _question(7)),
    )

    rendered = render_interview_reference(reference, [7, 2, 7, 5])

    assert rendered.count("## 本轮重点题目（完整内容）") == 1
    assert (
        rendered.index("### Q7") < rendered.index("### Q2") < rendered.index("### Q5")
    )
    assert "- 候选人回答: 回答 7" in rendered
    assert "- 优化回答: 优化回答 2" in rendered
    assert "- 知识点: 知识点 5" in rendered
    assert rendered.index("## 本轮重点题目") < rendered.index("## 综合表现")
    assert rendered.index("## 综合表现") < rendered.index("## 候选人简历全文")


def test_reference_keeps_full_answers_out_of_the_default_question_index():
    reference = InterviewReference(
        record_id="record-1",
        title="后端面试",
        tag="",
        source="upload",
        status="completed",
        analysis_json=None,
        resume_text="",
        audio_file_asset_id=None,
        resume_id=None,
        resume_file_asset_id=None,
        jd_file_asset_id=None,
        questions=(_question(2),),
    )

    rendered = render_interview_reference(reference)

    assert "Q2 · 2/10: 问题 2" in rendered
    assert "回答 2" not in rendered
