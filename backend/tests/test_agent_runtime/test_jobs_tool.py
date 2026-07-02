"""search_jobs tool — availability check_fn + network error handling."""

import asyncio


class TestSearchJobsCheckFn:
    """search_jobs must be hidden from the manifest when LEVER_SITES is empty."""

    def test_jobs_hidden_when_lever_sites_empty(self, monkeypatch):
        monkeypatch.setattr("app.core.config.settings.LEVER_SITES", "")
        from app.agent_runtime.tools.jobs import _jobs_available
        assert _jobs_available() is False

    def test_jobs_visible_when_lever_sites_set(self, monkeypatch):
        monkeypatch.setattr("app.core.config.settings.LEVER_SITES", "acme-corp")
        from app.agent_runtime.tools.jobs import _jobs_available
        assert _jobs_available() is True

    def test_handler_returns_error_when_no_sites(self, monkeypatch):
        monkeypatch.setattr("app.core.config.settings.LEVER_SITES", "")
        from app.agent_runtime.tool_registry import AgentToolContext
        from app.agent_runtime.tools.jobs import SearchJobsArgs, _search_jobs_handler
        ctx = AgentToolContext(user_id="alice", session_id="s1")
        result = asyncio.run(_search_jobs_handler(
            SearchJobsArgs(keywords="backend"), ctx,
        ))
        assert "error" in result
        assert result["count"] == 0


class TestSearchJobsErrorHandling:
    """search_jobs must catch httpx errors gracefully."""

    def test_per_site_timeout_skipped_gracefully(self, monkeypatch):
        """Per-site timeouts are caught and skipped — result is empty, not an error."""
        import httpx as _httpx

        monkeypatch.setattr("app.core.config.settings.LEVER_SITES", "acme")
        monkeypatch.setattr("app.core.config.settings.LEVER_API_BASE", "https://api.lever.co/v0")

        class _TimeoutClient(_httpx.AsyncClient):
            async def get(self, *a, **kw):
                raise _httpx.TimeoutException("timed out")

        monkeypatch.setattr("httpx.AsyncClient", _TimeoutClient)

        from app.agent_runtime.tool_registry import AgentToolContext
        from app.agent_runtime.tools.jobs import SearchJobsArgs, _search_jobs_handler
        ctx = AgentToolContext(user_id="alice", session_id="s1")
        result = asyncio.run(_search_jobs_handler(
            SearchJobsArgs(keywords="backend"), ctx,
        ))
        assert result["count"] == 0
        assert result["jobs"] == []

    def test_unexpected_error_returns_error_dict(self, monkeypatch):
        """Non-httpx exceptions (e.g. JSON decode, network) are caught at outer level."""
        monkeypatch.setattr("app.core.config.settings.LEVER_SITES", "acme")
        monkeypatch.setattr("app.core.config.settings.LEVER_API_BASE", "https://api.lever.co/v0")

        class _BrokenClient:
            async def __aenter__(self):
                raise OSError("DNS resolution failed")
            async def __aexit__(self, *a):
                pass

        monkeypatch.setattr("httpx.AsyncClient", lambda **kw: _BrokenClient())

        from app.agent_runtime.tool_registry import AgentToolContext
        from app.agent_runtime.tools.jobs import SearchJobsArgs, _search_jobs_handler
        ctx = AgentToolContext(user_id="alice", session_id="s1")
        result = asyncio.run(_search_jobs_handler(
            SearchJobsArgs(keywords="backend"), ctx,
        ))
        assert "error" in result
