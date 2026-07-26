from evaluation.metrics import (
    aggregate_scores,
    hit_at_k,
    ndcg_at_k,
    overlap_score,
    percentile,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)


def test_overlap_score_handles_english_and_chinese() -> None:
    assert overlap_score("MCP isolation", "MCP needs per-user isolation") == 1.0
    assert overlap_score("混合检索", "这里解释混合检索的原理") == 1.0


def test_binary_ranking_metrics_respect_k() -> None:
    flags = [False, True, True]
    assert hit_at_k(flags, 1) == 0
    assert hit_at_k(flags, 2) == 1
    assert precision_at_k(flags, 2) == 0.5
    assert recall_at_k(flags, total_relevant=2, k=2) == 0.5
    assert reciprocal_rank(flags) == 0.5


def test_ndcg_rewards_better_ordering() -> None:
    assert ndcg_at_k([3.0, 2.0, 0.0]) == 1.0
    assert ndcg_at_k([0.0, 2.0, 3.0]) < 1.0
    assert ndcg_at_k([]) == 0.0


def test_percentile_interpolates_and_aggregate_handles_empty() -> None:
    assert percentile([0.0, 10.0], 0.5) == 5.0
    assert aggregate_scores([]) == {
        "mean": 0.0,
        "min": 0.0,
        "max": 0.0,
        "p50": 0.0,
        "p95": 0.0,
    }
