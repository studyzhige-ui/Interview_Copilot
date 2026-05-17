"""Tests for the per-user BM25 retriever cache.

Covers:
  * cache-key isolation across user_id / source_type combinations
  * TTL-based expiry on individual entries
  * Per-user invalidation (other users untouched)
  * Build path: when the docstore is empty or no nodes match the scope,
    no entry is cached.

The retriever module shadows ``app.rag.retriever`` re-exports the cache
helpers from ``app.rag.bm25_cache`` — both import paths are tested so a
future refactor that breaks the re-export gets caught.
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────────
# Key isolation
# ─────────────────────────────────────────────────────────────────────


def test_bm25_cache_key_isolation_by_user_and_source():
    from app.rag.bm25_cache import _bm25_cache_key

    key_alice_qa = _bm25_cache_key("alice", "interview_qa")
    key_bob_qa = _bm25_cache_key("bob", "interview_qa")
    key_alice_docs = _bm25_cache_key("alice", "official_docs")
    key_alice_none = _bm25_cache_key("alice", None)

    keys = {key_alice_qa, key_bob_qa, key_alice_docs, key_alice_none}
    assert len(keys) == 4, "Each (user, source) combination must produce a unique key"
    # The empty source slot is serialised consistently.
    assert key_alice_none.endswith("|*")


def test_bm25_cache_key_re_export_from_retriever():
    """``retriever`` re-exports cache helpers; the symbol must stay identical."""
    from app.rag import bm25_cache as direct
    from app.rag import retriever as via_retriever

    assert via_retriever._bm25_cache_key is direct._bm25_cache_key
    assert via_retriever._bm25_cache is direct._bm25_cache
    assert via_retriever.invalidate_bm25_cache is direct.invalidate_bm25_cache


# ─────────────────────────────────────────────────────────────────────
# TTL / expiry
# ─────────────────────────────────────────────────────────────────────


def test_bm25_cache_entry_fresh_is_not_expired():
    from app.rag.bm25_cache import _BM25CacheEntry

    entry = _BM25CacheEntry(retriever=MagicMock(), node_count=7)
    assert entry.node_count == 7
    assert entry.expired is False


def test_bm25_cache_entry_expires_after_ttl():
    from app.rag.bm25_cache import _BM25_CACHE_TTL, _BM25CacheEntry

    entry = _BM25CacheEntry(retriever=MagicMock(), node_count=1)
    # Back-date the creation time past TTL.
    entry.created_at = time.monotonic() - _BM25_CACHE_TTL - 1
    assert entry.expired is True


def test_get_cached_bm25_returns_none_when_entry_expired():
    """An expired entry should not be returned by `_get_cached_bm25`."""
    from app.rag.bm25_cache import (
        _BM25_CACHE_TTL,
        _BM25CacheEntry,
        _bm25_cache,
        _bm25_cache_lock,
        _get_cached_bm25,
    )

    fake = MagicMock()
    with _bm25_cache_lock:
        entry = _BM25CacheEntry(fake, 5)
        entry.created_at = time.monotonic() - _BM25_CACHE_TTL - 1
        _bm25_cache["expired|*"] = entry

    try:
        got = _get_cached_bm25("expired", None, ["expired"])
        assert got is None, "Expired entry must not be served"
    finally:
        with _bm25_cache_lock:
            _bm25_cache.pop("expired|*", None)


def test_get_cached_bm25_returns_fresh_entry():
    from app.rag.bm25_cache import (
        _BM25CacheEntry,
        _bm25_cache,
        _bm25_cache_lock,
        _get_cached_bm25,
    )

    sentinel = MagicMock(name="sentinel-retriever")
    with _bm25_cache_lock:
        _bm25_cache["fresh|interview_qa"] = _BM25CacheEntry(sentinel, 3)

    try:
        got = _get_cached_bm25("fresh", "interview_qa", ["fresh"])
        assert got is sentinel
    finally:
        with _bm25_cache_lock:
            _bm25_cache.pop("fresh|interview_qa", None)


# ─────────────────────────────────────────────────────────────────────
# Invalidation
# ─────────────────────────────────────────────────────────────────────


def test_invalidate_bm25_cache_only_clears_target_user():
    from app.rag.bm25_cache import (
        _BM25CacheEntry,
        _bm25_cache,
        _bm25_cache_lock,
        invalidate_bm25_cache,
    )

    with _bm25_cache_lock:
        _bm25_cache["alice|interview_qa"] = _BM25CacheEntry(MagicMock(), 5)
        _bm25_cache["alice|official_docs"] = _BM25CacheEntry(MagicMock(), 3)
        _bm25_cache["bob|interview_qa"] = _BM25CacheEntry(MagicMock(), 8)

    invalidate_bm25_cache("alice")

    try:
        with _bm25_cache_lock:
            assert "alice|interview_qa" not in _bm25_cache
            assert "alice|official_docs" not in _bm25_cache
            assert "bob|interview_qa" in _bm25_cache, \
                "Other users' caches must survive invalidation"
    finally:
        with _bm25_cache_lock:
            _bm25_cache.pop("bob|interview_qa", None)


def test_invalidate_bm25_cache_no_op_when_user_absent():
    """Calling invalidate for a user with no entries is harmless."""
    from app.rag.bm25_cache import _bm25_cache, _bm25_cache_lock, invalidate_bm25_cache

    with _bm25_cache_lock:
        snapshot = dict(_bm25_cache)

    invalidate_bm25_cache("nonexistent-user-xyz")

    with _bm25_cache_lock:
        assert dict(_bm25_cache) == snapshot


def test_invalidate_does_not_match_user_id_as_substring():
    """User ``alice`` and ``alice-2`` must be isolated — prefix-only matching."""
    from app.rag.bm25_cache import (
        _BM25CacheEntry,
        _bm25_cache,
        _bm25_cache_lock,
        invalidate_bm25_cache,
    )

    with _bm25_cache_lock:
        _bm25_cache["alice|*"] = _BM25CacheEntry(MagicMock(), 1)
        _bm25_cache["alice-2|*"] = _BM25CacheEntry(MagicMock(), 1)

    invalidate_bm25_cache("alice")

    try:
        with _bm25_cache_lock:
            assert "alice|*" not in _bm25_cache
            # The pipe delimiter in the key prevents alice-2 matching alice's prefix.
            assert "alice-2|*" in _bm25_cache
    finally:
        with _bm25_cache_lock:
            _bm25_cache.pop("alice-2|*", None)


# ─────────────────────────────────────────────────────────────────────
# Build path — uses mocked PostgresDocumentStore
# ─────────────────────────────────────────────────────────────────────


def test_build_and_cache_bm25_returns_none_when_docstore_empty():
    """No nodes in the docstore → no cache entry, returns None."""
    from app.rag import bm25_cache as mod

    fake_store = MagicMock()
    fake_store.docs = {}

    with patch.object(mod, "PostgresDocumentStore") as fake_cls:
        fake_cls.from_uri.return_value = fake_store
        result = mod._build_and_cache_bm25(
            user_id="u-empty",
            source_type=None,
            allowed_user_ids=["u-empty"],
            metadata_matches_scope=lambda meta, allowed, st: True,
        )
    assert result is None
    with mod._bm25_cache_lock:
        assert "u-empty|*" not in mod._bm25_cache


def test_build_and_cache_bm25_returns_none_when_scope_filters_everything():
    from app.rag import bm25_cache as mod

    other_user_node = MagicMock()
    other_user_node.metadata = {"user_id": "other", "source_type": "interview_qa"}

    fake_store = MagicMock()
    fake_store.docs = {"id1": other_user_node}

    def scope(meta, allowed, st):
        return meta.get("user_id") in allowed

    with patch.object(mod, "PostgresDocumentStore") as fake_cls:
        fake_cls.from_uri.return_value = fake_store
        result = mod._build_and_cache_bm25(
            user_id="alice",
            source_type=None,
            allowed_user_ids=["alice"],
            metadata_matches_scope=scope,
        )
    assert result is None
    with mod._bm25_cache_lock:
        assert "alice|*" not in mod._bm25_cache


def test_build_and_cache_bm25_swallows_errors_and_returns_none():
    """A failure inside Postgres connection should degrade quietly."""
    from app.rag import bm25_cache as mod

    with patch.object(mod, "PostgresDocumentStore") as fake_cls:
        fake_cls.from_uri.side_effect = RuntimeError("PG down")
        result = mod._build_and_cache_bm25(
            user_id="u-err",
            source_type=None,
            allowed_user_ids=["u-err"],
            metadata_matches_scope=lambda meta, allowed, st: True,
        )
    assert result is None
