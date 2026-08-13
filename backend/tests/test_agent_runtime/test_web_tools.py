"""read_url / web_search tools — content limits, injection marker, errors.

SSRF URL validation lives in test_web_tool_ssrf.py.
"""

import asyncio
from types import SimpleNamespace


def _resolved(url: str):
    return SimpleNamespace(
        connect_url=url,
        host_header="example.com",
        sni_hostname="example.com",
    )


class TestReadUrlImprovements:
    """read_url improvements: size limit, content limit, injection marker."""

    def test_external_content_notice_prepended(self, monkeypatch):
        """read_url must prepend a prompt-injection defense marker."""

        class _FakeResponse:
            status_code = 200
            url = "https://example.com"
            headers = {"content-type": "text/plain"}
            text = "Hello world"
            content = b"Hello world"
            encoding = "utf-8"

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def aiter_bytes(self):
                yield self.content

        class _FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

            def stream(self, *a, **kw):
                return _FakeResponse()

        monkeypatch.setattr("httpx.AsyncClient", lambda **kw: _FakeClient())
        monkeypatch.setattr(
            "app.agent_runtime.tools.web._resolve_safe_url",
            _resolved,
        )

        from app.agent_runtime.tool_registry import AgentToolContext
        from app.agent_runtime.tools.web import ReadUrlArgs, _read_url_handler

        ctx = AgentToolContext(user_id="alice", session_id="s1")
        result = asyncio.run(
            _read_url_handler(ReadUrlArgs(url="https://example.com"), ctx)
        )
        assert "error" not in result
        assert result["content"].startswith("[External web content below")
        assert "Hello world" in result["content"]

    def test_oversized_response_rejected(self, monkeypatch):
        """HTTP responses exceeding _MAX_HTTP_BYTES must be refused."""

        class _FakeResponse:
            status_code = 200
            url = "https://example.com/huge"
            headers = {"content-type": "text/html"}
            text = "x" * 100
            content = b"x" * (6 * 1024 * 1024)  # 6 MB > 5 MB limit
            encoding = "utf-8"

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def aiter_bytes(self):
                yield self.content[: 3 * 1024 * 1024]
                yield self.content[3 * 1024 * 1024 :]

        class _FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

            def stream(self, *a, **kw):
                return _FakeResponse()

        monkeypatch.setattr("httpx.AsyncClient", lambda **kw: _FakeClient())
        monkeypatch.setattr(
            "app.agent_runtime.tools.web._resolve_safe_url",
            _resolved,
        )

        from app.agent_runtime.tool_registry import AgentToolContext
        from app.agent_runtime.tools.web import ReadUrlArgs, _read_url_handler

        ctx = AgentToolContext(user_id="alice", session_id="s1")
        result = asyncio.run(
            _read_url_handler(ReadUrlArgs(url="https://example.com/huge"), ctx)
        )
        assert "error" in result
        assert "too large" in result["error"].lower()

    def test_content_truncated_at_max_chars(self, monkeypatch):
        """Content exceeding _MAX_CONTENT_CHARS must be truncated."""
        from app.agent_runtime.tools.web import _MAX_CONTENT_CHARS

        class _FakeResponse:
            status_code = 200
            url = "https://example.com/long"
            headers = {"content-type": "text/plain"}
            text = "A" * (_MAX_CONTENT_CHARS + 10_000)
            content = text.encode()
            encoding = "utf-8"

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def aiter_bytes(self):
                yield self.content

        class _FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

            def stream(self, *a, **kw):
                return _FakeResponse()

        monkeypatch.setattr("httpx.AsyncClient", lambda **kw: _FakeClient())
        monkeypatch.setattr(
            "app.agent_runtime.tools.web._resolve_safe_url",
            _resolved,
        )

        from app.agent_runtime.tool_registry import AgentToolContext
        from app.agent_runtime.tools.web import ReadUrlArgs, _read_url_handler

        ctx = AgentToolContext(user_id="alice", session_id="s1")
        result = asyncio.run(
            _read_url_handler(ReadUrlArgs(url="https://example.com/long"), ctx)
        )
        assert result["truncated"] is True
        assert result["char_count"] == _MAX_CONTENT_CHARS

    def test_html_noise_tags_stripped(self, monkeypatch):
        """HTML noise tags (nav, footer, script) must be stripped."""
        from app.agent_runtime.tools.web import _html_to_markdown

        html = """
        <html><body>
        <nav><a href="/">Home</a><a href="/about">About</a></nav>
        <main><p>Important article content here.</p></main>
        <footer>Copyright 2024</footer>
        <script>alert('xss')</script>
        </body></html>
        """
        md = _html_to_markdown(html)
        assert "Important article content" in md
        assert "alert" not in md
        assert "Copyright" not in md


class TestWebSearchErrorHandling:
    """web_search must catch network errors gracefully."""

    def test_timeout_returns_error_dict(self, monkeypatch):
        import httpx as _httpx

        monkeypatch.setenv("TAVILY_API_KEY", "test-key")

        class _TimeoutClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

            async def post(self, *a, **kw):
                raise _httpx.TimeoutException("timed out")

        monkeypatch.setattr("httpx.AsyncClient", lambda **kw: _TimeoutClient())

        from app.agent_runtime.tool_registry import AgentToolContext
        from app.agent_runtime.tools.web import WebSearchArgs, _web_search_handler

        ctx = AgentToolContext(user_id="alice", session_id="s1")
        result = asyncio.run(
            _web_search_handler(
                WebSearchArgs(query="test"),
                ctx,
            )
        )
        assert "error" in result
        assert "timed out" in result["error"].lower()
