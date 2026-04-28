import asyncio


def test_function_calling_agent_runtime_shared_session(monkeypatch):
    from app.agent_runtime import react_agent as runtime

    class FakeUsage:
        prompt_tokens = 10
        completion_tokens = 5

    class FakeFunction:
        def __init__(self, name: str, arguments: str):
            self.name = name
            self.arguments = arguments

    class FakeToolCall:
        def __init__(self, call_id: str, name: str, arguments: str):
            self.id = call_id
            self.function = FakeFunction(name, arguments)

    class FakeMessage:
        def __init__(self, content: str, tool_calls):
            self.content = content
            self.tool_calls = tool_calls

    class FakeChoice:
        def __init__(self, message):
            self.message = message

    class FakeResponse:
        def __init__(self, message):
            self.choices = [FakeChoice(message)]
            self.usage = FakeUsage()

    class FakeCompletions:
        def __init__(self):
            self.calls = 0

        async def create(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return FakeResponse(
                    FakeMessage(
                        content="",
                        tool_calls=[
                            FakeToolCall("call_1", "echo", '{"text":"hello"}'),
                        ],
                    )
                )
            return FakeResponse(FakeMessage(content="final answer", tool_calls=[]))

    class FakeClient:
        def __init__(self):
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    class FakeTranscriptService:
        def __init__(self):
            self.calls = []

        def ensure_session(self, session_id, user_id):
            self.calls.append(("ensure", session_id, user_id))

        def append_turn(self, **kwargs):
            self.calls.append(("append", kwargs))
            return 2

    class FakeInterviewStateService:
        def __init__(self):
            self.calls = []

        def ensure_state(self, session_id, user_id):
            self.calls.append((session_id, user_id))

    class FakeContextPipeline:
        def assemble_answer_context(self, **kwargs):
            from dataclasses import dataclass

            @dataclass
            class FakeCtx:
                context_text: str = "ctx"

            return FakeCtx()

    class FakeTool:
        async def execute(self, args, ctx):
            return {"echo": args.get("text"), "session_id": ctx.session_id}

    class FakeMaintenance:
        def __init__(self):
            self.calls = []

        async def run(self, session_id, user_id):
            self.calls.append((session_id, user_id))

    created_runs = []
    steps = []
    finished_runs = []
    maintenance = FakeMaintenance()
    transcript = FakeTranscriptService()

    async def fake_create_run(user_id: str, session_id: str, goal: str, mode: str):
        created_runs.append((user_id, session_id, goal, mode))
        return "run_123"

    async def fake_append_step(**kwargs):
        steps.append(kwargs)

    async def fake_finish_run(**kwargs):
        finished_runs.append(kwargs)

    async def fake_recall_relevant(user_id: str, query: str):
        return [{"id": "m1", "type": "user_profile", "description": "senior", "content": "senior backend"}]

    monkeypatch.setattr(runtime, "build_async_openai_client_for_role", lambda role: (FakeClient(), type("Profile", (), {"model": "fake-model"})()))
    monkeypatch.setattr(runtime, "transcript_service", transcript)
    monkeypatch.setattr(runtime, "interview_state_service", FakeInterviewStateService())
    monkeypatch.setattr(runtime, "context_pipeline", FakeContextPipeline())
    monkeypatch.setattr(runtime, "memory_retrieval_service", type("MemorySvc", (), {"recall_relevant": staticmethod(fake_recall_relevant)})())
    monkeypatch.setattr(runtime, "build_default_tool_registry", lambda: {"echo": FakeTool()})
    monkeypatch.setattr(runtime, "build_openai_tool_schemas", lambda registry: [{"type": "function", "function": {"name": "echo", "parameters": {"type": "object"}}}])
    monkeypatch.setattr(runtime, "format_tool_manifest", lambda registry: "[]")
    monkeypatch.setattr(runtime, "create_run", fake_create_run)
    monkeypatch.setattr(runtime, "append_step", fake_append_step)
    monkeypatch.setattr(runtime, "finish_run", fake_finish_run)
    monkeypatch.setattr(runtime, "post_turn_maintenance_service", maintenance)

    result = asyncio.run(runtime.run_react_agent("help me", "alice", "s1"))

    assert result["run_id"] == "run_123"
    assert result["reply"] == "final answer"
    assert result["tool_calls"] == 1
    assert created_runs[0][1] == "s1"
    assert any(step["action_type"] == "tool_call" for step in steps)
    assert any(step["action_type"] == "final_answer" for step in steps)
    assert finished_runs[0]["status"] == "completed"
    assert transcript.calls[0] == ("ensure", "s1", "alice")
    assert transcript.calls[1][1]["session_id"] == "s1"


def test_agent_budget_stop(monkeypatch):
    from app.agent_runtime import react_agent as runtime

    class FakeTranscriptService:
        def ensure_session(self, session_id, user_id):
            return None

        def append_turn(self, **kwargs):
            return 1

    class FakeInterviewStateService:
        def ensure_state(self, session_id, user_id):
            return None

    class FakeContextPipeline:
        def assemble_answer_context(self, **kwargs):
            from dataclasses import dataclass

            @dataclass
            class FakeCtx:
                context_text: str = ""

            return FakeCtx()

    async def fake_create_run(user_id: str, session_id: str, goal: str, mode: str):
        return "run_budget"

    appended = []
    finished = []

    async def fake_append_step(**kwargs):
        appended.append(kwargs)

    async def fake_finish_run(**kwargs):
        finished.append(kwargs)

    async def fake_recall_relevant(user_id: str, query: str):
        return []

    monkeypatch.setattr(runtime, "transcript_service", FakeTranscriptService())
    monkeypatch.setattr(runtime, "interview_state_service", FakeInterviewStateService())
    monkeypatch.setattr(runtime, "context_pipeline", FakeContextPipeline())
    monkeypatch.setattr(runtime, "memory_retrieval_service", type("MemorySvc", (), {"recall_relevant": staticmethod(fake_recall_relevant)})())
    monkeypatch.setattr(runtime, "create_run", fake_create_run)
    monkeypatch.setattr(runtime, "append_step", fake_append_step)
    monkeypatch.setattr(runtime, "finish_run", fake_finish_run)
    monkeypatch.setattr(runtime, "post_turn_maintenance_service", type("Maintenance", (), {"run": staticmethod(fake_recall_relevant)})())
    monkeypatch.setattr(runtime.settings, "AGENT_MAX_STEPS", 0)

    result = asyncio.run(runtime.run_react_agent("goal", "alice", "s2"))

    assert result["budget_stop_reason"] == "max_steps_exceeded"
    assert finished[0]["status"] == "stopped"
    assert any(step["action_type"] == "budget_stop" for step in appended)
