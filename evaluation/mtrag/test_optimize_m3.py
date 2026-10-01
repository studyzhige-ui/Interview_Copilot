import unittest

from .optimize_m3 import BASELINE, candidates, grid, split_tasks
from .run import fusion


class OptimizationContracts(unittest.TestCase):
    def test_transitive_duplicate_conversations_cannot_cross_split(self):
        tasks = []
        for i in range(20):
            for turn in range(2):
                tasks.append(
                    {
                        "query_id": f"a{i}-{turn}",
                        "dataset": "a",
                        "domain": "d",
                        "conversation_id": str(i),
                        "input_sha256": f"input{i}-{turn}",
                    }
                )
        tasks.extend(
            [
                {
                    "query_id": "b1",
                    "dataset": "b",
                    "domain": "d",
                    "conversation_id": "b",
                    "input_sha256": "input0-0",
                },
                {
                    "query_id": "b2",
                    "dataset": "b",
                    "domain": "d",
                    "conversation_id": "b",
                    "input_sha256": "input1-0",
                },
            ]
        )
        result = split_tasks(tasks)
        for i in range(20):
            self.assertEqual(result[f"a{i}-0"], result[f"a{i}-1"])
        for key in ("a0-0", "a0-1", "a1-0", "a1-1", "b1", "b2"):
            self.assertEqual(result[key], result["b1"])
        self.assertEqual(result, split_tasks(list(reversed(tasks))))
        self.assertEqual({r["split"] for r in result.values()}, {"tune", "validation"})

    def test_baseline_preserves_existing_rrf_ranking(self):
        retrieved = {
            "dense": [str(i) for i in range(100)],
            "bm25": [str(i) for i in range(40, 140)],
        }
        expected, _ = fusion(retrieved["bm25"][:50], retrieved["dense"][:50])
        self.assertEqual(candidates(retrieved, BASELINE), expected)

    def test_grid_candidates_covered_by_scored_union_and_budgets(self):
        retrieved = {
            "dense": [str(i) for i in range(100)],
            "bm25": [str(i) for i in range(50, 150)],
        }
        union = set(retrieved["dense"] + retrieved["bm25"])
        for config in grid():
            ids = candidates(retrieved, config)
            self.assertEqual(len(ids), config["rerank_k"] or 10)
            self.assertEqual(len(set(ids)), len(ids))
            self.assertTrue(set(ids) <= union)
            if config["dense_weight"] == 1:
                self.assertEqual(ids, retrieved["dense"][: config["rerank_k"] or 10])


if __name__ == "__main__":
    unittest.main()
