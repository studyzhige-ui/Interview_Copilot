"""测试 retriever.py 中 BM25 per-user 缓存的隔离、过期与失效逻辑。"""
import time


def test_bm25_cache_key_isolation():
    """不同 user_id / source_type 组合应生成不同的缓存键。"""
    from app.rag.retriever import _bm25_cache_key

    key_a = _bm25_cache_key("alice", "interview_qa")
    key_b = _bm25_cache_key("bob", "interview_qa")
    key_c = _bm25_cache_key("alice", "official_docs")
    key_d = _bm25_cache_key("alice", None)

    assert key_a != key_b, "不同用户应有不同缓存键"
    assert key_a != key_c, "不同 source_type 应有不同缓存键"
    assert key_a != key_d, "有/无 source_type 应有不同缓存键"


def test_bm25_cache_entry_expiry():
    """缓存条目超过 TTL 后应标记为过期。"""
    from app.rag.retriever import _BM25CacheEntry, _BM25_CACHE_TTL

    entry = _BM25CacheEntry(retriever=None, node_count=10)
    assert not entry.expired, "刚创建的条目不应过期"

    # Simulate TTL expiry by backdating created_at
    entry.created_at = time.monotonic() - _BM25_CACHE_TTL - 1
    assert entry.expired, "超过 TTL 的条目应标记为过期"


def test_bm25_cache_invalidation():
    """invalidate_bm25_cache 应只清除指定用户的缓存条目。"""
    from app.rag.retriever import (
        _bm25_cache,
        _bm25_cache_lock,
        _BM25CacheEntry,
        invalidate_bm25_cache,
    )

    # Seed the cache with entries for two users
    with _bm25_cache_lock:
        _bm25_cache["alice|interview_qa"] = _BM25CacheEntry(None, 5)
        _bm25_cache["alice|official_docs"] = _BM25CacheEntry(None, 3)
        _bm25_cache["bob|interview_qa"] = _BM25CacheEntry(None, 8)

    invalidate_bm25_cache("alice")

    with _bm25_cache_lock:
        assert "alice|interview_qa" not in _bm25_cache
        assert "alice|official_docs" not in _bm25_cache
        assert "bob|interview_qa" in _bm25_cache, "其他用户的缓存不应被清除"

    # Cleanup
    with _bm25_cache_lock:
        _bm25_cache.pop("bob|interview_qa", None)
