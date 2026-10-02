"""Small analytic fixtures for corpus scoring and stage composition."""

import math
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from . import run
from .run import BM25, fusion, score_ranking, topk
from .profile import load_profile


class MetricTests(unittest.TestCase):
    def test_bm25_matches_hand_calculated_term_score(self):
        model = BM25(
            [{"text": "apple apple banana"}, {"text": "banana"}, {"text": "carrot"}]
        )
        expected = (
            math.log(1 + (3 - 1 + 0.5) / (1 + 0.5))
            * (2 * 2.2)
            / (2 + 1.2 * (0.25 + 0.75 * 3 / (5 / 3)))
        )
        scores = model.search("apple")
        self.assertAlmostEqual(float(scores[0]), expected, places=6)
        self.assertEqual(topk(scores, positive=True).tolist(), [0])
        self.assertEqual(
            topk(model.search("notinthecorpus"), positive=True).tolist(), []
        )

    def test_recall_counts_all_positives_and_ndcg_uses_rank(self):
        metrics = score_ranking(["wrong", "a"], {"a": 1, "b": 1})
        self.assertEqual(metrics["recall@10"], 0.5)
        self.assertEqual(metrics["hit@10"], 1)
        expected = (1 / math.log2(3)) / (1 + 1 / math.log2(3))
        self.assertAlmostEqual(metrics["ndcg@10"], expected)
        with self.assertRaises(ValueError):
            score_ranking(["a", "a"], {"a": 1})

    def test_rrf_equal_weight_and_dedup(self):
        ids, scores = fusion(["a", "b"], ["b", "c"])
        self.assertEqual(ids, ["b", "a", "c"])
        self.assertAlmostEqual(scores[0], 1 / 61 + 1 / 62)

    def test_identical_rerank_requests_share_inference_without_losing_rows(self):
        tasks = [
            {
                "key": mode,
                "query_id": mode,
                "mode": mode,
                "query": "same query",
                "domain": "clapnq",
                "dataset": "test",
                "qrels": {"a": 1},
            }
            for mode in ("last_turn", "deepseek_rewrite")
        ]
        candidates = [
            {
                "key": t["key"],
                "ids": ["a", "b"],
                "metrics": {"recall@50": 1},
                "timings_ms": {"total": 1},
            }
            for t in tasks
        ]
        fake = MagicMock()
        fake.truncation = {}
        fake.rerank.side_effect = [run.np.array([0.0]), run.np.array([1.0, 0.0])]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "runs").mkdir()
            for family in ("bge",):
                (root / "runs" / f"bm25_{family}.jsonl").write_text(
                    "\n".join(json.dumps(row) for row in candidates), encoding="utf-8"
                )
            with (
                patch.object(run, "ROOT", root),
                patch.object(run, "DOMAINS", ("clapnq",)),
                patch.object(run, "LocalModel", return_value=fake),
                patch.object(
                    run,
                    "corpus",
                    return_value=[{"_id": "a", "text": "A"}, {"_id": "b", "text": "B"}],
                ),
                patch.object(run.torch.cuda, "synchronize"),
                patch.object(run.torch.cuda, "reset_peak_memory_stats"),
                patch.object(run.torch.cuda, "max_memory_allocated", return_value=0),
            ):
                run.rerank(load_profile(), tasks, "test-campaign", "bge")
            output = [
                row
                for family in ("bge",)
                for row in run.read_rows(
                    root / "runs" / f"bm25_{family}_rerank_bge.jsonl"
                )
            ]
            self.assertEqual(fake.rerank.call_count, 2)  # warmup + one real inference
            self.assertEqual(len(output), 4)
            self.assertEqual(
                sum(row["reused_identical_inference"] for row in output), 3
            )
            self.assertTrue(all(row["metrics"]["ndcg@10"] == 1 for row in output))


if __name__ == "__main__":
    unittest.main()
