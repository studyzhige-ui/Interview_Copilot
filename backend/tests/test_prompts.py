"""Prompt-template contracts and organization guardrails."""

from __future__ import annotations

import ast
from pathlib import Path

from app.prompts.chat import (
    CONVERSATION_COMPACTION_PROMPT,
    build_query_planner_system_prompt,
)
from app.prompts.interview import (
    DEBRIEF_SUMMARY_PROMPT,
    MOCK_INTERVIEW_NEXT_TURN_PROMPT,
    MOCK_INTERVIEW_PREFIX,
)
from app.prompts.memory import (
    DOC_COMPACT_PROMPT,
    DREAMING_PROMPT,
    REALTIME_EXTRACTION_PROMPT,
)
from app.prompts.resume import RESUME_PARSE_PROMPT
from app.prompts.voice_analysis import (
    BATCH_ANALYSIS_PROMPT,
    PER_QUESTION_ANALYSIS_PROMPT,
    QA_EXTRACTION_PROMPT,
    SYNTHESIS_PROMPT,
)


def test_all_prompt_templates_render() -> None:
    rendered = [
        CONVERSATION_COMPACTION_PROMPT.format(
            old_summary="old", new_conversation="new"
        ),
        DEBRIEF_SUMMARY_PROMPT.format(
            title="title",
            tag="tag",
            overall_text="analysis",
            qa_lines="questions",
            transcript_excerpt="transcript",
        ),
        MOCK_INTERVIEW_PREFIX.format(resume="resume", jd="jd", style="style"),
        MOCK_INTERVIEW_NEXT_TURN_PROMPT.format(
            prefix="prefix",
            stage_list="stages",
            current_stage="technical",
            recent_dialog="dialog",
            asked_trunc=40,
            asked_questions="questions",
            questions_in_current_stage=2,
            min_questions=2,
            max_questions=4,
            transition_rule="可推进",
            user_answer="answer",
            stage_keys_hint="technical | candidate_questions",
        ),
        REALTIME_EXTRACTION_PROMPT.format(
            user_profile="profile",
            learning_strategy="strategy",
            ability_index="abilities",
            conversation="conversation",
        ),
        DREAMING_PROMPT.format(
            record_id="record",
            user_profile="profile",
            learning_strategy="strategy",
            ability_index="abilities",
            record_messages="messages",
            record_debrief_summary="summary",
        ),
        DOC_COMPACT_PROMPT.format(
            max_lines=10,
            doc_label="profile",
            line_count=20,
            char_count=1000,
            body="body",
        ),
        RESUME_PARSE_PROMPT.format(resume_text="resume"),
        QA_EXTRACTION_PROMPT.format(transcript="transcript", resume_hint="resume"),
        PER_QUESTION_ANALYSIS_PROMPT.format(
            resume_section="resume",
            jd_section="jd",
            context_section="context",
            index=1,
            total=1,
            question="question",
            answer="answer",
        ),
        SYNTHESIS_PROMPT.format(
            resume_context="resume",
            jd_context="jd",
            per_question_summary="analysis",
        ),
        BATCH_ANALYSIS_PROMPT.format(
            resume_context="resume",
            jd_context="jd",
            prev_ctx="previous",
            batch_block="batch",
            next_ctx="next",
        ),
    ]

    assert all(rendered)
    assert '"sections"' in rendered[7]
    assert '"qa_pairs"' in rendered[8]
    assert '"patches"' in rendered[4]
    assert '"patches"' in rendered[5]


def test_query_planner_memory_privacy_contract() -> None:
    enabled = build_query_planner_system_prompt(
        global_memory_on=True,
        max_sub_queries=3,
    )
    disabled = build_query_planner_system_prompt(
        global_memory_on=False,
        max_sub_queries=3,
    )

    assert "at most 3" in enabled
    assert "load_strategy=true" in enabled
    assert "load_strategy must be false" in disabled


def test_long_prompt_constants_live_in_prompt_package() -> None:
    app_root = Path(__file__).parents[1] / "app"
    offenders: list[str] = []

    for path in app_root.rglob("*.py"):
        if path.parent == app_root / "prompts":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            names = (
                [target.id for target in node.targets if isinstance(target, ast.Name)]
                if isinstance(node, ast.Assign)
                else [node.target.id]
                if isinstance(node.target, ast.Name)
                else []
            )
            if (
                any("PROMPT" in name for name in names)
                and isinstance(value, ast.Constant)
                and isinstance(value.value, str)
                and len(value.value) >= 120
            ):
                offenders.append(str(path.relative_to(app_root)))

    assert offenders == []
