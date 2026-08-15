"""read_url / web_search tools — content limits, injection marker, errors.

SSRF URL validation lives in test_web_tool_ssrf.py.
"""

import asyncio
from types import SimpleNamespace

# Import the tool module before tests replace ``httpx.AsyncClient``.  The
# package also registers provider-backed tools whose SDK classes subclass the
# real httpx client at import time; replacing it first corrupts that unrelated
# class definition in a fresh pytest process.
from app.agent_runtime.tools import web as _web_tool  # noqa: F401


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


class TestWebSearchFallback:
    """web_search falls back without turning deployment config into waiting."""

    def test_tavily_timeout_falls_back_to_duckduckgo(self, monkeypatch):
        import httpx as _httpx

        monkeypatch.setenv("TAVILY_API_KEY", "test-key")

        class _TimeoutClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

            async def post(self, *a, **kw):
                raise _httpx.TimeoutException("timed out")

            async def get(self, *a, **kw):
                return _httpx.Response(
                    200,
                    request=_httpx.Request("GET", str(a[0])),
                    text=(
                        '<div class="result">'
                        '<a class="result__a" href="//duckduckgo.com/l/?uddg='
                        'https%3A%2F%2Fexample.com%2Fjobs">Example jobs</a>'
                        '<div class="result__snippet">A useful result</div>'
                        '</div>'
                    ),
                )

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
        assert result["source"] == "duckduckgo"
        assert result["fallback_from"] == "tavily_timeout"
        assert result["results"][0]["url"] == "https://example.com/jobs"

    def test_missing_tavily_key_uses_public_fallback_without_connection_prompt(
        self, monkeypatch
    ):
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)

        import httpx as _httpx

        class _DuckClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

            async def get(self, *a, **kw):
                return _httpx.Response(
                    200,
                    request=_httpx.Request("GET", str(a[0])),
                    text=(
                        '<div class="result">'
                        '<a class="result__a" href="https://example.com">Example</a>'
                        '</div>'
                    ),
                )

        monkeypatch.setattr("httpx.AsyncClient", lambda **kw: _DuckClient())

        from app.agent_runtime.tool_registry import AgentToolContext, registry
        from app.agent_runtime.tools.web import WebSearchArgs, _web_search_handler

        ctx = AgentToolContext(user_id="alice", session_id="s1")
        plan = asyncio.run(registry.plan_call("web_search", {"query": "test"}, ctx))
        assert plan.connection_ready is True
        assert plan.hard_deny_reason is None

        result = asyncio.run(
            _web_search_handler(
                WebSearchArgs(query="test"),
                ctx,
            )
        )

        assert result["source"] == "duckduckgo"
        assert result["fallback_from"] == "tavily_not_configured"
        assert result["count"] == 1
