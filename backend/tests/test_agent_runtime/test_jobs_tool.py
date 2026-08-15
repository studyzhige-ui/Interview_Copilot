"""search_jobs tool — call-time connection preflight and network handling."""

import asyncio


class TestSearchJobsConnectionPreflight:
    """A real Tool stays discoverable and reports missing connection at call time."""

    def test_tool_remains_registered_without_lever_configuration(self, monkeypatch):
        monkeypatch.setattr("app.core.config.settings.LEVER_SITES", "")
        from app.agent_runtime.tool_registry import registry

        assert "search_jobs" in registry

    def test_missing_deployment_config_is_hard_denied(self, monkeypatch):
        monkeypatch.setattr("app.core.config.settings.LEVER_SITES", "")
        from app.agent_runtime.tool_registry import AgentToolContext
        from app.agent_runtime.tool_registry import registry

        ctx = AgentToolContext(user_id="alice", session_id="s1")
        plan = asyncio.run(
            registry.plan_call("search_jobs", {"keywords": "backend"}, ctx)
        )
        assert plan.connection_ready is False
        assert plan.hard_deny_reason == "connector_unavailable"

    def test_handler_returns_typed_error_when_no_sites(self, monkeypatch):
        monkeypatch.setattr("app.core.config.settings.LEVER_SITES", "")
        from app.agent_runtime.tool_registry import AgentToolContext
        from app.agent_runtime.tools.jobs import SearchJobsArgs, _search_jobs_handler

        result = asyncio.run(
            _search_jobs_handler(
                SearchJobsArgs(keywords="backend"),
                AgentToolContext(user_id="alice", session_id="s1"),
            )
        )
        assert result == {
            "error": "connector_unavailable",
            "provider": "lever",
            "reason": "deployment_configuration_missing",
            "count": 0,
        }


class TestSearchJobsErrorHandling:
    """search_jobs must catch httpx errors gracefully."""

    def test_per_site_timeout_skipped_gracefully(self, monkeypatch):
        """Per-site timeouts are caught and skipped — result is empty, not an error."""
        import httpx as _httpx

        monkeypatch.setattr("app.core.config.settings.LEVER_SITES", "acme")
        monkeypatch.setattr(
            "app.core.config.settings.LEVER_API_BASE", "https://api.lever.co/v0"
        )

        class _TimeoutClient(_httpx.AsyncClient):
            async def get(self, *a, **kw):
                raise _httpx.TimeoutException("timed out")

        monkeypatch.setattr("httpx.AsyncClient", _TimeoutClient)

        from app.agent_runtime.tool_registry import AgentToolContext
        from app.agent_runtime.tools.jobs import SearchJobsArgs, _search_jobs_handler

        ctx = AgentToolContext(user_id="alice", session_id="s1")
        result = asyncio.run(
            _search_jobs_handler(
                SearchJobsArgs(keywords="backend"),
                ctx,
            )
        )
        assert result["error"] == "lever_sites_unreachable"
        assert result["timed_out_sites"] == ["acme"]
        assert result["count"] == 0
        assert result["jobs"] == []

    def test_invalid_site_slug_is_reported_instead_of_silent_empty_result(
        self, monkeypatch
    ):
        import httpx as _httpx

        monkeypatch.setattr("app.core.config.settings.LEVER_SITES", "not-a-site")

        class _NotFoundClient(_httpx.AsyncClient):
            async def get(self, *a, **kw):
                return _httpx.Response(404)

        monkeypatch.setattr("httpx.AsyncClient", _NotFoundClient)

        from app.agent_runtime.tool_registry import AgentToolContext
        from app.agent_runtime.tools.jobs import SearchJobsArgs, _search_jobs_handler

        result = asyncio.run(
            _search_jobs_handler(
                SearchJobsArgs(keywords="backend"),
                AgentToolContext(user_id="alice", session_id="s1"),
            )
        )
        assert result["error"] == "lever_sites_invalid"
        assert result["invalid_sites"] == ["not-a-site"]

    def test_unexpected_error_returns_error_dict(self, monkeypatch):
        """Non-httpx exceptions (e.g. JSON decode, network) are caught at outer level."""
        monkeypatch.setattr("app.core.config.settings.LEVER_SITES", "acme")
        monkeypatch.setattr(
            "app.core.config.settings.LEVER_API_BASE", "https://api.lever.co/v0"
        )

        class _BrokenClient:
            async def __aenter__(self):
                raise OSError("DNS resolution failed")

            async def __aexit__(self, *a):
                pass

        monkeypatch.setattr("httpx.AsyncClient", lambda **kw: _BrokenClient())

        from app.agent_runtime.tool_registry import AgentToolContext
        from app.agent_runtime.tools.jobs import SearchJobsArgs, _search_jobs_handler

        ctx = AgentToolContext(user_id="alice", session_id="s1")
        result = asyncio.run(
            _search_jobs_handler(
                SearchJobsArgs(keywords="backend"),
                ctx,
            )
        )
        assert "error" in result
