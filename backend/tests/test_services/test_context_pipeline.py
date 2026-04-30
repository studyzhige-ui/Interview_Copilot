from app.services.context_service import ContextBundle, PromptRenderer


def test_prompt_renderer_keeps_expected_context_order():
    renderer = PromptRenderer()
    bundle = ContextBundle(
        working_state={"goal": "redis"},
        interview_state={"phase": "probing"},
        relevant_memories=[
            {
                "type": "interaction_preference",
                "description": "Language",
                "content": "User prefers Chinese answers.",
            }
        ],
        knowledge_chunks=[
            {
                "source_type": "interview_qa",
                "score": 0.9,
                "text": "Redis cache avalanche means many keys expire together.",
            }
        ],
        recent_turns=[
            {"role": "User", "content": "What is cache avalanche?"},
            {"role": "Agent", "content": "It is a cache failure pattern."},
        ],
        current_query="How do I answer it in interviews?",
    )

    prompt = renderer.render_answer_prompt(bundle, system_rules="System rules")

    assert prompt.index("System rules") < prompt.index("[Working State]")
    assert prompt.index("[Working State]") < prompt.index("[Long-term Memories]")
    assert prompt.index("[Long-term Memories]") < prompt.index("[Retrieved Knowledge]")
    assert prompt.index("[Retrieved Knowledge]") < prompt.index("[Recent Turns]")
    assert prompt.index("[Recent Turns]") < prompt.index("[Current Query]")
