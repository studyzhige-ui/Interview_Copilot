"""Prompt-template contracts and organization guardrails."""

from __future__ import annotations

import ast
from pathlib import Path

from app.prompts.chat import (
    CONVERSATION_COMPACTION_PROMPT,
    build_query_planner_system_prompt,
)
from app.prompts.interview import (
    MOCK_INTERVIEW_NEXT_TURN_PROMPT,
    MOCK_INTERVIEW_PLAN_PROMPT,
    MOCK_INTERVIEW_PREFIX,
)
from app.prompts.memory import (
    DOC_COMPACT_PROMPT,
    DREAMING_PROMPT,
    REALTIME_EXTRACTION_PROMPT,
)
from app.prompts.resume import RESUME_PARSE_PROMPT
from app.prompts.voice_analysis import (
    QA_EXTRACTION_PROMPT,
    QUESTION_ANALYSIS_PROMPT,
    SYNTHESIS_PROMPT,
)


def test_all_prompt_templates_render() -> None:
    rendered = [
        CONVERSATION_COMPACTION_PROMPT.format(
            old_summary="old", new_conversation="new"
        ),
        MOCK_INTERVIEW_PREFIX.format(resume="resume", jd="jd", style="style"),
        MOCK_INTERVIEW_PLAN_PROMPT.format(
            resume="resume",
            jd="jd",
            style="style",
        ),
        MOCK_INTERVIEW_NEXT_TURN_PROMPT.format(
            prefix="prefix",
            stage_list="stages",
            current_stage="technical",
            response_language="简体中文",
            length_warning_active="false",
            pacing_instruction="自然推进",
            conversation_history="dialog",
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
            record_analysis_context="summary",
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
        QUESTION_ANALYSIS_PROMPT.format(
            resume_context="resume",
            jd_context="jd",
            prev_ctx="previous",
            batch_block="batch",
            next_ctx="next",
        ),
        SYNTHESIS_PROMPT.format(
            resume_context="resume",
            jd_context="jd",
            per_question_summary="analysis",
        ),
    ]

    assert all(rendered)
    assert any('"sections"' in prompt for prompt in rendered)
    assert any('"qa_pairs"' in prompt for prompt in rendered)
    assert sum('"patches"' in prompt for prompt in rendered) >= 2


def test_query_planner_memory_privacy_contract() -> None:
    enabled = build_query_planner_system_prompt(
        global_memory_on=True,
        max_intents=3,
    )
    disabled = build_query_planner_system_prompt(
        global_memory_on=False,
        max_intents=3,
    )

    assert "at most 3" in enabled
    assert "load_strategy=true" in enabled
    assert '"alternate_query"' in enabled
    assert '"required_terms"' in enabled
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
