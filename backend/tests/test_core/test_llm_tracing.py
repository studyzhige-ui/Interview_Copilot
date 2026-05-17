"""Tests for app.core.llm_tracing — opt-in LangSmith monkey-patch of openai.OpenAI."""
from __future__ import annotations

import importlib
import logging

import pytest


@pytest.fixture
def fresh_tracing(monkeypatch):
    """Reload the module so the _PATCHED module-global resets, and undo any patch
    of openai.OpenAI / openai.AsyncOpenAI that earlier tests may have left behind.

    Also stubs out :func:`app.core.llm_tracing._ensure_dotenv_loaded` to a no-op
    so the fixture's ``monkeypatch.delenv("LANGSMITH_*")`` calls aren't undone
    when the function re-reads ``.env`` from disk. (Production needs the
    dotenv reload because main.py imports llm_tracing before app.core.config —
    but in tests we want full env-var control.)
    """
    import openai

    saved_sync = openai.OpenAI
    saved_async = openai.AsyncOpenAI

    import app.core.llm_tracing as llm_tracing
    llm_tracing = importlib.reload(llm_tracing)
    monkeypatch.setattr(llm_tracing, "_ensure_dotenv_loaded", lambda: None)

    yield llm_tracing

    # Restore openai so other modules keep behaving normally.
    openai.OpenAI = saved_sync
    openai.AsyncOpenAI = saved_async
    # Reset the module-global so subsequent imports in this process start clean.
    llm_tracing._PATCHED = False


def test_setup_is_noop_when_tracing_env_unset(monkeypatch, fresh_tracing):
    import openai

    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)

    before_sync = openai.OpenAI
    before_async = openai.AsyncOpenAI

    activated = fresh_tracing.setup_llm_tracing()

    assert activated is False
    assert openai.OpenAI is before_sync
    assert openai.AsyncOpenAI is before_async
    assert fresh_tracing._PATCHED is False


def test_setup_is_noop_when_tracing_false(monkeypatch, fresh_tracing):
    import openai

    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2_anything")

    before_sync = openai.OpenAI
    activated = fresh_tracing.setup_llm_tracing()

    assert activated is False
    assert openai.OpenAI is before_sync


def test_setup_warns_when_tracing_true_but_no_api_key(monkeypatch, fresh_tracing, caplog):
    import openai

    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)

    before_sync = openai.OpenAI
    with caplog.at_level(logging.WARNING, logger="app.core.llm_tracing"):
        activated = fresh_tracing.setup_llm_tracing()

    assert activated is False
    assert openai.OpenAI is before_sync
    assert any("LANGSMITH_API_KEY" in r.getMessage() for r in caplog.records)


def test_setup_patches_openai_when_enabled(monkeypatch, fresh_tracing):
    import openai

    # Stub langsmith.wrappers.wrap_openai so the test doesn't need the real lib.
    import sys
    import types

    stub_module = types.ModuleType("langsmith.wrappers")
    sentinel_marker = object()

    def fake_wrap(client):
        # Tag the returned client so we can prove the wrapper ran.
        client._lc_wrapped = sentinel_marker
        return client

    stub_module.wrap_openai = fake_wrap
    parent = types.ModuleType("langsmith")
    parent.wrappers = stub_module
    monkeypatch.setitem(sys.modules, "langsmith", parent)
    monkeypatch.setitem(sys.modules, "langsmith.wrappers", stub_module)

    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2_fake_key")
    monkeypatch.setenv("LANGSMITH_PROJECT", "icp-tests")

    before_sync = openai.OpenAI
    before_async = openai.AsyncOpenAI

    activated = fresh_tracing.setup_llm_tracing()

    assert activated is True
    assert fresh_tracing._PATCHED is True
    assert openai.OpenAI is not before_sync
    assert openai.AsyncOpenAI is not before_async

    # Instantiate a client and verify wrap_openai ran.
    client = openai.OpenAI(api_key="sk-test")
    assert getattr(client, "_lc_wrapped", None) is sentinel_marker


def test_setup_is_idempotent(monkeypatch, fresh_tracing):
    import openai
    import sys
    import types

    stub_module = types.ModuleType("langsmith.wrappers")
    stub_module.wrap_openai = lambda c: c
    parent = types.ModuleType("langsmith")
    parent.wrappers = stub_module
    monkeypatch.setitem(sys.modules, "langsmith", parent)
    monkeypatch.setitem(sys.modules, "langsmith.wrappers", stub_module)

    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2_fake_key")

    first = fresh_tracing.setup_llm_tracing()
    patched_sync_after_first = openai.OpenAI
    patched_async_after_first = openai.AsyncOpenAI

    second = fresh_tracing.setup_llm_tracing()

    assert first is True
    assert second is True
    # Second call must not re-wrap (i.e. the same patched factories stay in place).
    assert openai.OpenAI is patched_sync_after_first
    assert openai.AsyncOpenAI is patched_async_after_first


def test_setup_handles_missing_langsmith_gracefully(monkeypatch, fresh_tracing, caplog):
    import openai
    import sys
    import builtins

    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2_fake_key")

    # Ensure no real or stub langsmith is cached.
    monkeypatch.delitem(sys.modules, "langsmith", raising=False)
    monkeypatch.delitem(sys.modules, "langsmith.wrappers", raising=False)

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "langsmith.wrappers" or name.startswith("langsmith"):
            raise ImportError("simulated: langsmith not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    before_sync = openai.OpenAI
    with caplog.at_level(logging.WARNING, logger="app.core.llm_tracing"):
        activated = fresh_tracing.setup_llm_tracing()

    assert activated is False
    assert openai.OpenAI is before_sync
    assert any("import failed" in r.getMessage() for r in caplog.records)
