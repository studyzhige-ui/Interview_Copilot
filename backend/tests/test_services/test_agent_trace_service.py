import asyncio


def test_agent_trace_service_crud(monkeypatch, db_session):
    from app.services import agent_trace_service as svc

    monkeypatch.setattr(svc, "SessionLocal", lambda: db_session)

    run_id = asyncio.run(svc.create_run(user_id="alice", session_id="s1", goal="find jobs"))
    assert run_id

    asyncio.run(
        svc.append_step(
            run_id=run_id,
            step_index=1,
            action_type="tool_call",
            tool_name="search_jobs",
            tool_call_id="call_1",
            tool_args={"keywords": "python"},
            observation={"count": 2},
            assistant_content="",
            is_error=False,
            latency_ms=12.3,
        )
    )

    asyncio.run(
        svc.finish_run(
            run_id=run_id,
            status="completed",
            final_answer="done",
            steps_used=2,
            tool_calls=1,
            prompt_tokens=100,
            completion_tokens=20,
            total_latency_ms=234.5,
        )
    )

    run_payload = asyncio.run(svc.get_run_with_steps(run_id=run_id, user_id="alice"))
    assert run_payload is not None
    assert run_payload["status"] == "completed"
    assert run_payload["steps"][0]["tool_name"] == "search_jobs"

    run_list = asyncio.run(svc.list_runs(user_id="alice", session_id="s1", limit=10, offset=0))
    assert len(run_list) == 1

    metrics = asyncio.run(svc.aggregate_trajectory_metrics(user_id="alice", session_id="s1"))
    assert metrics["run_count"] == 1
    assert metrics["avg_tool_calls"] == 1.0
