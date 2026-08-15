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
from app.prompts.resume import RESUME_PARSE_PROMPT
from app.prompts.interview_transcript_structure import (
    QA_EPISODE_PROMPT,
    SPEAKER_ROLE_PROMPT,
    UTTERANCE_STRUCTURE_PROMPT,
)
from app.prompts.voice_analysis import QUESTION_ANALYSIS_PROMPT, SYNTHESIS_PROMPT


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
        RESUME_PARSE_PROMPT.format(resume_text="resume"),
        SPEAKER_ROLE_PROMPT.format(turns="turns"),
        UTTERANCE_STRUCTURE_PROMPT.format(roles="roles", window="window"),
        QA_EPISODE_PROMPT.format(utterances="utterances"),
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
    assert any('"question_utterance_ids"' in prompt for prompt in rendered)


def test_query_planner_schema_contract() -> None:
    prompt = build_query_planner_system_prompt(max_intents=3)

    assert "at most 3" in prompt
    assert '"alternate_query"' in prompt
    assert '"required_terms"' in prompt
    assert "load_strategy" not in prompt


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
