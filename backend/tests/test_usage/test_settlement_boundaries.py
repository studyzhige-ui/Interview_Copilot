"""Accounting failures must survive every provider adapter and fallback layer.

Only transports and a COMMIT acknowledgement are substituted. Admission, owner
attribution, settlement and ledger readback use the actual implementation.
"""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.execution_errors import (
    ConsumptionSettlementUnconfirmedError,
    ModelOutcomeUnknownError,
)
from app.usage.service import ModelBudgetExceededError
from app.models.model_budget import ModelBudgetReservation, ModelBudgetWindow
from app.usage import external


@pytest.mark.parametrize("gateway", ["request", "stream", "mcp", "cloud"])
@pytest.mark.parametrize("lost_after_commit", [False, True])
def test_provider_completion_settles_once_even_if_commit_is_unconfirmed(
    usage_scope, monkeypatch, tmp_path, gateway, lost_after_commit
):
    armed = False
    commits = []
    dispatches = []
    closed = []
    original_commit = usage_scope.class_.commit

    def commit(db):
        if not armed:
            return original_commit(db)
        commits.append("settlement")
        if lost_after_commit:
            original_commit(db)
        raise OSError("synthetic settlement acknowledgement lost")

    monkeypatch.setattr(usage_scope.class_, "commit", commit)

    def completed():
        nonlocal armed
        dispatches.append("provider-completed")
        armed = True
        return SimpleNamespace(status_code=200, num_bytes_downloaded=3)

    async def send():
        return completed()

    @asynccontextmanager
    async def open_response():
        try:
            yield completed()
        finally:
            closed.append(True)

    async def streamed():
        async with external.stream(
            open_response,
            provider="fixture",
            operation="read",
            content="synthetic",
            max_bytes=64,
        ):
            pass

    manager = server = None
    if gateway == "mcp":
        from app.agent_runtime.mcp.manager import MCPManager, _ServerRuntime

        config = SimpleNamespace(user_id=1, id=7, revision="1")
        server = _ServerRuntime(config)

        class DeliveredQueue:
            def put_nowait(self, request):
                request.started = True
                request.future.set_result(completed())

        server.queue = DeliveredQueue()
        manager = MCPManager()
        monkeypatch.setattr(manager, "_get_runtime", AsyncMock(return_value=server))
        monkeypatch.setattr(manager, "_discard", AsyncMock())

    if gateway == "cloud":
        from app.rag.parsing import cloud

        path = tmp_path / "synthetic.docx"
        path.write_bytes(b"not private content")
        monkeypatch.setattr(settings, "LLAMA_CLOUD_API_KEY", "fixture")
        monkeypatch.setattr(settings, "CLOUD_PARSE_TIER", "cost_effective")
        client_type = httpx.Client

        def handle(request):
            if request.method == "POST":
                return httpx.Response(200, json={"id": "fixture-job"})
            completed()
            return httpx.Response(
                200,
                json={
                    "job": {"id": "fixture-job", "status": "COMPLETED"},
                    "markdown": {
                        "pages": [{"page_number": 1, "markdown": "synthetic result"}]
                    },
                },
            )

        monkeypatch.setattr(
            cloud.httpx,
            "Client",
            lambda **kw: client_type(transport=httpx.MockTransport(handle), **kw),
        )

    with pytest.raises(ConsumptionSettlementUnconfirmedError):
        if gateway == "request":
            asyncio.run(
                external.request(
                    send, provider="fixture", operation="read", content="synthetic"
                )
            )
        elif gateway == "stream":
            asyncio.run(streamed())
        elif gateway == "mcp":
            asyncio.run(manager._request(config, "call_tool", {"name": "fixture"}))
        else:
            cloud.parse(str(path))

    assert dispatches == ["provider-completed"]
    assert commits == ["settlement"], "an unconfirmed COMMIT is not a retry permit"
    if gateway == "stream":
        assert closed == [True]
    if manager is not None:
        manager._discard.assert_not_awaited()
        assert server.pending == 0
    with usage_scope() as db:
        row = db.scalar(select(ModelBudgetReservation))
        assert row.status == ("settled" if lost_after_commit else "reserved")
        window = db.get(ModelBudgetWindow, (row.user_id, row.window_date))
        assert window.calls_admitted == 1
        assert window.units_reserved_json["requests"] == (0 if lost_after_commit else 1)


@pytest.mark.parametrize(
    "handler", ["tavily", "duckduckgo", "jobs", "job_detail", "url"]
)
@pytest.mark.asyncio
async def test_tool_fallbacks_propagate_unconfirmed_settlement(monkeypatch, handler):
    from app.agent_runtime.tool_registry import AgentToolContext
    from app.agent_runtime.tools import web, jobs

    error = ConsumptionSettlementUnconfirmedError("consumption_settlement_unconfirmed")
    send = AsyncMock(side_effect=error)
    monkeypatch.setattr(web, "metered_request", send)
    monkeypatch.setattr(jobs, "metered_request", send)
    monkeypatch.setattr(web, "_resolve_tavily_key", lambda _user: "fixture")
    monkeypatch.setattr(settings, "LEVER_SITES", "fixture-one,fixture-two")
    ctx = AgentToolContext(user_id="alice", session_id="fixture")
    if handler == "tavily":
        fallback = AsyncMock()
        monkeypatch.setattr(web, "_search_duckduckgo", fallback)
        call = web._web_search_handler(web.WebSearchArgs(query="fixture"), ctx)
    elif handler == "duckduckgo":
        call = web._search_duckduckgo(web.WebSearchArgs(query="fixture"))
    elif handler == "jobs":
        call = jobs._search_jobs_handler(jobs.SearchJobsArgs(keywords="fixture"), ctx)
    elif handler == "job_detail":
        call = jobs._fetch_detail("fixture", ["fixture-one", "fixture-two"])
    else:
        monkeypatch.setattr(
            web,
            "_resolve_safe_url",
            lambda url: SimpleNamespace(
                connect_url=url, host_header="example.com", sni_hostname=None
            ),
        )

        @asynccontextmanager
        async def failed_stream(*args, **kwargs):
            raise error
            yield  # pragma: no cover -- declares the async context-manager protocol

        monkeypatch.setattr(web, "metered_stream", failed_stream)
        call = web._read_url_handler(web.ReadUrlArgs(url="https://example.com/"), ctx)
    with pytest.raises(ConsumptionSettlementUnconfirmedError) as caught:
        await call
    assert caught.value is error
    if handler == "tavily":
        fallback.assert_not_awaited()
    if handler != "url":
        send.assert_awaited_once()


@pytest.mark.parametrize(
    "error_type",
    [
        ConsumptionSettlementUnconfirmedError,
        ModelOutcomeUnknownError,
        ModelBudgetExceededError,
    ],
)
def test_parser_selection_does_not_mask_a_nonretryable_consumption_error(error_type):
    from app.rag.parsing.registry import _run_candidates

    error = error_type("synthetic_nonretryable_consumption_error")
    tried = []

    class First:
        id, tier = "cloud-fixture", "first_class"

        def parse(self, path):
            tried.append(self.id)
            raise error

    class Fallback(First):
        id = "local-fixture"

    with pytest.raises(error_type) as caught:
        _run_candidates("synthetic.docx", [First(), Fallback()])
    assert caught.value is error
    assert tried == ["cloud-fixture"]


def test_completed_but_truncated_cloud_parse_is_settled_once(
    usage_scope, monkeypatch, tmp_path
):
    from app.rag.parsing import cloud

    path = tmp_path / "synthetic.docx"
    path.write_bytes(b"synthetic source")
    monkeypatch.setattr(settings, "LLAMA_CLOUD_API_KEY", "fixture")
    monkeypatch.setattr(settings, "CLOUD_PARSE_TIER", "cost_effective")
    monkeypatch.setattr(settings, "CLOUD_PARSE_MAX_PAGES", 1)
    client_type = httpx.Client
    requests = []
    commits = []
    original_commit = usage_scope.class_.commit

    def commit(db):
        commits.append("commit")
        return original_commit(db)

    def handle(request):
        requests.append(request.method)
        if request.method == "POST":
            return httpx.Response(200, json={"id": "fixture-job"})
        # Only count settlement after provider completion, not admission or the
        # saved job identity. This output reaches the non-paginated-file limit.
        monkeypatch.setattr(usage_scope.class_, "commit", commit)
        return httpx.Response(
            200,
            json={
                "job": {"id": "fixture-job", "status": "COMPLETED"},
                "markdown": {"pages": [{"page_number": 1, "markdown": "partial"}]},
            },
        )

    monkeypatch.setattr(
        cloud.httpx,
        "Client",
        lambda **kw: client_type(transport=httpx.MockTransport(handle), **kw),
    )
    with pytest.raises(ValueError, match="cloud_parse_coverage_incomplete"):
        cloud.parse(str(path))
    assert requests == ["POST", "GET"]
    assert commits == ["commit"]
    with usage_scope() as db:
        row = db.scalar(select(ModelBudgetReservation))
        assert row.status == "settled"
        assert row.observed_units_json["pages"] == 1
        window = db.get(ModelBudgetWindow, (row.user_id, row.window_date))
        assert window.calls_admitted == 1
        assert window.units_reserved_json["requests"] == 0
