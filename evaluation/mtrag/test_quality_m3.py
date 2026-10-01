import unittest
from .quality_m3 import pools, rank


class QualityContracts(unittest.TestCase):
    def test_candidate_preservation_is_monotonic(self):
        task = {"key": "rewrite::q", "query_id": "q"}
        source = {
            "bge_m3_dense": {
                "rewrite::q": {"ids": ["a", "b"]},
                "last_turn::q": {"ids": ["d", "a"]},
            },
            "bm25": {
                "rewrite::q": {"ids": ["b", "c"]},
                "last_turn::q": {"ids": ["e", "c"]},
            },
            "bm25_bge_m3": {"rewrite::q": {"ids": ["b", "a"]}},
        }
        p = pools(task, source)
        self.assertLessEqual(set(p["baseline"]), set(p["preserve_channels"]))
        self.assertLessEqual(
            set(p["preserve_channels"]), set(p["add_original_retrieval"])
        )
        self.assertEqual(set(p["add_original_retrieval"]), {"a", "b", "c", "d", "e"})
        self.assertEqual(p["add_original_retrieval"], p["add_original_rerank"])

    def test_same_query_ranking_not_changed_by_dual_fusion(self):
        scores = {"a": -8.0, "b": 4.0, "c": 0.0}
        self.assertEqual(rank(list(scores), scores), rank(list(scores), scores, scores))

    def test_dual_ranking_preserves_candidates_and_deterministic_ties(self):
        first = {"a": 1.0, "b": 1.0, "c": 0.0}
        second = {"a": 0.0, "b": 3.0, "c": 4.0}
        output = rank(["c", "b", "a"], first, second)
        self.assertEqual(set(output), set(first))
        self.assertEqual(output, rank(["a", "b", "c"], first, second))


if __name__ == "__main__":
    unittest.main()
