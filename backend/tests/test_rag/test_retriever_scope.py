def test_allowed_user_ids_are_strictly_private():
    from app.rag import retriever

    allowed = retriever._allowed_user_ids("alice", "interview_qa")

    assert allowed == ["alice"]


def test_allowed_user_ids_keep_personal_memory_private():
    from app.rag import retriever

    assert retriever._allowed_user_ids("alice", "personal_memory") == ["alice"]


def test_metadata_scope_requires_allowed_user_and_source():
    from app.rag import retriever

    assert retriever._metadata_matches_scope(
        {"user_id": "alice", "source_type": "interview_qa"},
        ["alice"],
        "interview_qa",
    )
    assert not retriever._metadata_matches_scope(
        {"user_id": "bob", "source_type": "interview_qa"},
        ["alice", "public"],
        "interview_qa",
    )
    assert not retriever._metadata_matches_scope(
        {"user_id": "public", "source_type": "personal_memory"},
        ["alice", "public"],
        "interview_qa",
    )


def test_lexical_overlap_catches_close_redis_query():
    from app.rag import retriever

    query = "Redis 雪崩 击穿 穿透"
    content = "Redis 缓存雪崩、缓存击穿、缓存穿透分别是什么？应该如何解决？"

    assert retriever._lexical_overlap(query, content) >= 0.75


def test_fallback_score_threshold_uses_retriever_scale():
    from app.rag import retriever

    assert retriever._score_passes(0.03, min_score=0.5, used_reranker=False)
    assert not retriever._score_passes(0.03, min_score=0.5, used_reranker=True)
