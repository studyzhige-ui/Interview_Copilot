"""Offline checks for the benchmark's isolation and rewrite boundary."""

import json
import os
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import httpx

from .profile import comparison_matrix, load_profile, select_ranked_passages
from .rewrite import (
    CacheMissError,
    UnresolvedRequestError,
    cache_identity,
    request_body,
    rewrite_query,
)


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.profile = load_profile()
        self.record = {
            "query_id": "test",
            "messages": [
                {"role": "user", "content": "What is PostgreSQL?"},
                {"role": "assistant", "content": "A database system."},
                {"role": "user", "content": "How do I install it?"},
            ],
        }

    def test_app_environment_cannot_override_comparison(self):
        with patch.dict(
            os.environ,
            {
                "RAG_MIN_SCORE": "0.99",
                "RAG_FINAL_COUNT": "3",
                "INTERNAL_LLM_MODEL": "irrelevant-platform-model",
                "EMBEDDING_MODEL": "wrong-model",
            },
        ):
            self.assertEqual(load_profile(), self.profile)
            matrix = comparison_matrix(load_profile())
            self.assertEqual(len(matrix), 8)
            self.assertEqual(
                len({json.dumps(row, sort_keys=True) for row in matrix}), 8
            )

    def test_low_negative_scores_and_distinct_ids_survive(self):
        rows = [
            {"passage_id": str(i), "score": -i, "text": "identical text"}
            for i in range(15)
        ]
        rows.append({"passage_id": "0", "score": -100})
        output = select_ranked_passages(rows, self.profile)
        self.assertEqual(
            [row["passage_id"] for row in output], [str(i) for i in range(10)]
        )

    def test_gold_fields_and_current_answer_are_rejected(self):
        with self.assertRaises(ValueError):
            request_body({**self.record, "reference_answer": "gold"}, self.profile)
        record = {
            **self.record,
            "messages": self.record["messages"]
            + [{"role": "assistant", "content": "Current reference answer"}],
        }
        with self.assertRaises(ValueError):
            request_body(record, self.profile)

    def test_v2_retains_full_history_and_invalidates_only_prompt_cache(self):
        legacy = cache_identity(self.record, self.profile)[1]
        self.profile["rewrite"]["prompt_version"] = "v1"
        self.assertEqual(cache_identity(self.record, self.profile)[1], legacy)
        self.profile["rewrite"]["prompt_version"] = "v2"
        self.assertNotEqual(cache_identity(self.record, self.profile)[1], legacy)
        v2_key = cache_identity(self.record, self.profile)[1]
        self.profile["rewrite"]["prompt_version"] = "v2.1"
        self.assertNotEqual(cache_identity(self.record, self.profile)[1], v2_key)
        record = {
            "query_id": "long",
            "messages": [
                {"role": "user", "content": "最初的对象：数据库 A"},
                {"role": "assistant", "content": "历史正文。" * 3000},
                {"role": "user", "content": "回到最初的对象，如何安装？"},
            ],
        }
        body, original_key = cache_identity(record, self.profile)
        self.assertEqual(json.loads(body["messages"][1]["content"]), record["messages"])
        record["messages"][0]["content"] = "最初的对象：数据库 B"
        self.assertNotEqual(cache_identity(record, self.profile)[1], original_key)
        self.assertEqual(body["messages"][0]["role"], "system")

    def test_deepseek_request_and_cache_reuse(self):
        requests = []

        def respond(request):
            requests.append(request)
            body = json.loads(request.content)
            self.assertEqual(
                str(request.url), "https://api.deepseek.com/v1/chat/completions"
            )
            self.assertEqual(body["model"], "deepseek-flash")
            self.assertEqual(body["thinking"], {"type": "disabled"})
            self.assertEqual(body["temperature"], 0)
            return httpx.Response(
                200,
                json={
                    "model": "deepseek-flash",
                    "id": "mock",
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {
                                "content": '{"query":"How do I install PostgreSQL?"}'
                            },
                        }
                    ],
                    "usage": {"prompt_tokens": 20, "completion_tokens": 10},
                },
            )

        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            with httpx.Client(transport=httpx.MockTransport(respond)) as client:
                first = rewrite_query(
                    self.record,
                    self.profile,
                    client,
                    "test-secret",
                    cache,
                    allow_api=True,
                )
                second = rewrite_query(
                    {**self.record, "query_id": "another-id"},
                    self.profile,
                    client,
                    "",
                    cache,
                )
            self.assertEqual(len(requests), 1)
            self.assertFalse(first["cache_hit"])
            self.assertTrue(second["cache_hit"])
            self.assertEqual(second["query_id"], "another-id")
            self.assertEqual(first["query"], second["query"])
            self.assertNotIn("test-secret", next(cache.glob("*.json")).read_text())

    def test_truncated_response_does_not_become_a_query(self):
        calls = []

        def respond(request):
            calls.append(request)
            return httpx.Response(200, json={"choices": [{"finish_reason": "length"}]})

        with tempfile.TemporaryDirectory() as directory:
            with httpx.Client(transport=httpx.MockTransport(respond)) as client:
                for _ in range(2):
                    with self.assertRaises(ValueError):
                        rewrite_query(
                            self.record,
                            self.profile,
                            client,
                            "test",
                            Path(directory),
                            allow_api=True,
                        )
            self.assertEqual(list(Path(directory).glob("*.json")), [])
            self.assertEqual(len(calls), 1)

    @staticmethod
    def success_response():
        return httpx.Response(
            200,
            json={
                "model": "deepseek-flash",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": '{"query":"How do I install PostgreSQL?"}'
                        },
                    }
                ],
            },
        )

    def test_cache_only_mode_never_calls_network(self):
        def forbidden(request):
            self.fail("An ordinary evaluation must never populate missing rewrites")

        with tempfile.TemporaryDirectory() as directory:
            with httpx.Client(transport=httpx.MockTransport(forbidden)) as client:
                with self.assertRaises(CacheMissError):
                    rewrite_query(
                        self.record, self.profile, client, "key", Path(directory)
                    )

    def test_concurrent_preparation_sends_one_request(self):
        calls = []

        def respond(request):
            calls.append(request)
            time.sleep(0.05)
            return self.success_response()

        with tempfile.TemporaryDirectory() as directory:
            with httpx.Client(transport=httpx.MockTransport(respond)) as client:
                with ThreadPoolExecutor(max_workers=4) as pool:
                    results = list(
                        pool.map(
                            lambda _: rewrite_query(
                                self.record,
                                self.profile,
                                client,
                                "key",
                                Path(directory),
                                allow_api=True,
                            ),
                            range(4),
                        )
                    )
            self.assertEqual(len(calls), 1)
            self.assertEqual(sum(not row["cache_hit"] for row in results), 1)

    def test_uncertain_network_failure_is_not_retried_on_next_run(self):
        calls = []

        def timeout(request):
            calls.append(request)
            raise httpx.ReadTimeout("Unknown server completion state")

        with tempfile.TemporaryDirectory() as directory:
            with httpx.Client(transport=httpx.MockTransport(timeout)) as client:
                with self.assertRaises(httpx.ReadTimeout):
                    rewrite_query(
                        self.record,
                        self.profile,
                        client,
                        "key",
                        Path(directory),
                        allow_api=True,
                    )
                with self.assertRaises(UnresolvedRequestError):
                    rewrite_query(
                        self.record,
                        self.profile,
                        client,
                        "key",
                        Path(directory),
                        allow_api=True,
                    )
            self.assertEqual(len(calls), 1)

    def test_saved_response_recovers_after_interrupted_processing(self):
        calls = []

        def respond(request):
            calls.append(request)
            return self.success_response()

        with tempfile.TemporaryDirectory() as directory:
            with httpx.Client(transport=httpx.MockTransport(respond)) as client:
                first = rewrite_query(
                    self.record,
                    self.profile,
                    client,
                    "key",
                    Path(directory),
                    allow_api=True,
                )
            # Emulate losing the derived result after the raw receipt was saved.
            next(Path(directory).glob("*.json")).unlink()
            with httpx.Client(transport=httpx.MockTransport(respond)) as fresh_client:
                recovered = rewrite_query(
                    self.record, self.profile, fresh_client, "", Path(directory)
                )
            self.assertEqual(len(calls), 1)
            self.assertTrue(recovered["cache_hit"])
            self.assertEqual(first["query"], recovered["query"])

    def test_retrieval_settings_reuse_cache_but_generation_changes_miss(self):
        calls = []

        def respond(request):
            calls.append(request)
            return self.success_response()

        with tempfile.TemporaryDirectory() as directory:
            with httpx.Client(transport=httpx.MockTransport(respond)) as client:
                rewrite_query(
                    self.record,
                    self.profile,
                    client,
                    "key",
                    Path(directory),
                    allow_api=True,
                )
                self.profile["retrieval"]["output_k"] = 5
                self.assertTrue(
                    rewrite_query(
                        self.record, self.profile, client, "", Path(directory)
                    )["cache_hit"]
                )
                self.profile["rewrite"]["temperature"] = 0.5
                with self.assertRaises(CacheMissError):
                    rewrite_query(
                        self.record, self.profile, client, "key", Path(directory)
                    )
            self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
