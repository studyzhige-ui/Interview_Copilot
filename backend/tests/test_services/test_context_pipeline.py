from app.services.context_service import AssembledContext, PromptRenderer


def test_prompt_renderer_keeps_expected_context_order():
    renderer = PromptRenderer()
    ctx = AssembledContext(
        session_state={"mode": "general", "summary": "focusing on redis"},
        reference_material="",
        retrieved_context="[M1] [user_profile] Language: User prefers Chinese answers.\n\n[K1] [interview_qa score=0.900] Redis cache avalanche means many keys expire together.",
        recent_turns=[
            {"role": "User", "content": "What is cache avalanche?"},
            {"role": "Agent", "content": "It is a cache failure pattern."},
        ],
        current_input="How do I answer it in interviews?",
    )

    prompt = renderer.render_answer_prompt(ctx, system_rules="System rules")

    assert prompt.index("System rules") < prompt.index("[Retrieved Context]")
    assert prompt.index("[Retrieved Context]") < prompt.index("[Session State]")
    assert prompt.index("[Session State]") < prompt.index("[Recent Turns]")
    assert prompt.index("[Recent Turns]") < prompt.index("[Current Query]")
