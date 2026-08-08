from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from evaluation.llm_factory import TokenUsage, load_judge_llm_config
from evaluation.eval_runner import select_generation_evaluation_rows
from evaluation.metrics import (
    citation_coverage,
    citation_validity,
    has_insufficient_disclaimer,
    is_insufficient_answer,
    term_coverage,
)
from evaluation.report import _render_metric_table
from evaluation.runners import (
    _binary_ranking_metrics,
    _calibrate_threshold,
    _evidence_flags,
    _evidence_ndcg,
    _evidence_groups,
    _expected_document_ids,
    _is_successful_live_generation,
    _measure_stream,
    _resolve_gold_chunks,
    _source_format,
    _threshold_metrics,
    load_dataset,
)
from evaluation import ragas_runner
from evaluation.ragas_runner import formal_sample_manifest, select_formal_rows


def test_multi_document_evidence_groups_keep_atomic_gold_units() -> None:
    row = {
        "source_files": ["one.html", "two.pdf"],
        "evidence_groups": [
            {
                "source_file": "one.html",
                "alternatives": [
                    {"all_of": ["alpha", "beta"]},
                    {"all_of": ["equivalent"]},
                ],
            },
            {
                "source_file": "two.pdf",
                "alternatives": [{"all_of": ["gamma"]}],
            },
        ],
    }

    groups = _evidence_groups(row)

    assert [alternatives for _, alternatives in groups] == [
        (("alpha", "beta"), ("equivalent",)),
        (("gamma",),),
    ]
    assert len(_expected_document_ids(row)) == 2
    assert _source_format(row) == "mixed"


def test_evidence_flags_reward_each_group_once() -> None:
    flags, recall = _evidence_flags(
        ["group-a-primary", "group-a-duplicate", "noise", "group-b"],
        [
            {"group-a-primary", "group-a-duplicate"},
            {"group-b"},
        ],
    )

    assert flags == [True, False, False, True]
    assert recall == 1.0


def test_evidence_ndcg_treats_one_chunk_covering_two_groups_as_perfect() -> None:
    groups = [{"shared", "a-only"}, {"shared", "b-only"}]

    assert _evidence_ndcg(["shared"], groups) == 1.0
    assert _evidence_ndcg(["noise", "shared"], groups) < 1.0


def test_gold_chunk_alignment_reports_every_invalid_group(monkeypatch) -> None:
    chunks = [
        SimpleNamespace(
            document_id=_expected_document_ids({"source_file": "one.md"}).pop(),
            node_id="one-chunk",
            text="unrelated text",
        ),
        SimpleNamespace(
            document_id=_expected_document_ids({"source_file": "two.md"}).pop(),
            node_id="two-chunk",
            text="other unrelated text",
        ),
    ]

    class Query:
        def filter(self, *_args):
            return self

        def all(self):
            return chunks

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def query(self, _model):
            return Query()

    monkeypatch.setattr("app.db.database.SessionLocal", Session)
    rows = [
        {
            "id": "first",
            "source_file": "one.md",
            "evidence_groups": [
                {
                    "source_file": "one.md",
                    "alternatives": [{"all_of": ["missing one"]}],
                }
            ],
        },
        {
            "id": "second",
            "source_file": "two.md",
            "evidence_groups": [
                {
                    "source_file": "two.md",
                    "alternatives": [{"all_of": ["missing two"]}],
                }
            ],
        },
    ]

    with pytest.raises(RuntimeError) as error:
        _resolve_gold_chunks(rows)

    assert "first:group-1" in str(error.value)
    assert "second:group-1" in str(error.value)


def test_citation_metrics_do_not_split_python_identifiers() -> None:
    answer = (
        "协程取消会抛出 asyncio.CancelledError [K1]。\n清理应放在 try/finally 中 [K2]。"
    )

    assert citation_validity(answer, context_count=2) == 1.0
    assert citation_coverage(answer) == 1.0


def test_refusal_and_late_disclaimer_have_distinct_meanings() -> None:
    refusal = "资料不足，无法回答。"
    qualified_answer = "条件 A 时可以重试 [K1]。资料不足，无法确认条件 B。"

    assert is_insufficient_answer(refusal) is True
    assert has_insufficient_disclaimer(qualified_answer) is True
    assert is_insufficient_answer(qualified_answer) is False
    assert citation_coverage(qualified_answer) == 1.0


def test_term_coverage_is_case_insensitive() -> None:
    assert (
        term_coverage(["TaskGroup", "ExceptionGroup"], "taskgroup uses ExceptionGroup")
        == 1.0
    )
    assert term_coverage(["TaskGroup"], "The task group waits for completion") == 1.0


@pytest.mark.parametrize(
    ("api_base", "model", "expected"),
    [
        ("https://api.deepseek.com", "deepseek-v4-flash", "disabled"),
        ("https://example.test/v1", "other-model", None),
    ],
)
def test_evaluation_thinking_mode_is_provider_specific(
    monkeypatch: pytest.MonkeyPatch,
    api_base: str,
    model: str,
    expected: str | None,
) -> None:
    monkeypatch.setenv("EVAL_JUDGE_API_KEY", "test-key")
    monkeypatch.setenv("EVAL_JUDGE_API_BASE", api_base)
    monkeypatch.setenv("EVAL_JUDGE_MODEL", model)

    assert load_judge_llm_config().thinking_mode == expected


def test_default_deepseek_judge_uses_independent_pro_model(monkeypatch) -> None:
    for name in ("EVAL_JUDGE_API_KEY", "EVAL_JUDGE_API_BASE", "EVAL_JUDGE_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    config = load_judge_llm_config()

    assert config.api_base == "https://api.deepseek.com"
    assert config.model == "deepseek-v4-pro"


def test_ragas_judge_never_silently_falls_back_to_generator(monkeypatch) -> None:
    monkeypatch.setattr("evaluation.llm_factory.load_dotenv", lambda: None)
    for name in (
        "EVAL_JUDGE_API_KEY",
        "EVAL_JUDGE_API_BASE",
        "EVAL_JUDGE_MODEL",
        "DEEPSEEK_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(EnvironmentError, match="independent judge"):
        load_judge_llm_config()


def test_formal_ragas_sample_is_fixed_stratified_and_held_out() -> None:
    selected = select_formal_rows(load_dataset())

    assert len(selected) == 50
    assert {row["split"] for row in selected} == {"test"}
    assert {row["language"] for row in selected} == {"zh", "en"}
    assert sum(row["language"] == "zh" for row in selected) == 25
    assert sum(row["language"] == "en" for row in selected) == 25
    assert {
        difficulty: sum(row["difficulty"] == difficulty for row in selected)
        for difficulty in ("basic", "intermediate", "advanced")
    } == {"basic": 16, "intermediate": 17, "advanced": 17}
    source_files: set[str] = set()
    for row in selected:
        source_files.update(row.get("source_files") or [row["source_file"]])
    quotas = formal_sample_manifest()["quotas"]
    assert len(source_files) == quotas["source_documents"]
    assert sum(row["expected_intent_count"] == 2 for row in selected) == 4
    assert select_formal_rows(load_dataset(), compatibility_check=True) == selected[:1]


def test_formal_generation_excludes_calibration_negatives() -> None:
    selected = select_generation_evaluation_rows(load_dataset(), judge_limit=50)

    assert len([row for row in selected if row["expected_retrieval"] is True]) == 50
    assert all(row.get("split") == "test" for row in selected)


def test_deepseek_usage_cost_uses_cache_and_output_prices() -> None:
    usage = TokenUsage()
    before = usage.snapshot()
    usage.record(
        {
            "usage": {
                "prompt_tokens": 150,
                "prompt_cache_hit_tokens": 100,
                "prompt_cache_miss_tokens": 50,
                "completion_tokens": 20,
            }
        }
    )

    summary = usage.summary("deepseek-v4-pro")
    assert summary["requests"] == 1
    assert summary["input_tokens"] == 150
    assert summary["output_tokens"] == 20
    assert summary["estimated_cost_usd"] is not None
    assert usage.summary("deepseek-v4-pro", since=before)["requests"] == 1


def test_judge_usage_survives_resume(tmp_path) -> None:
    checkpoint = tmp_path / "usage.jsonl"
    first = TokenUsage(checkpoint_path=checkpoint)
    first.record(
        {
            "usage": {
                "prompt_tokens": 10,
                "prompt_cache_hit_tokens": 4,
                "prompt_cache_miss_tokens": 6,
                "completion_tokens": 3,
            }
        }
    )

    resumed = TokenUsage(checkpoint_path=checkpoint)

    assert resumed.requests == 1
    assert resumed.input_tokens == 10
    assert resumed.cache_hit_input_tokens == 4
    assert resumed.output_tokens == 3


@pytest.mark.asyncio
async def test_ragas_first_run_creates_lock_directory(monkeypatch, tmp_path) -> None:
    checkpoint_root = tmp_path / "nested" / "checkpoints"

    async def fake_score(scored_data, **_kwargs):
        return {"ragas_judged_samples": len(scored_data)}

    monkeypatch.setattr(ragas_runner, "CHECKPOINT_ROOT", checkpoint_root)
    monkeypatch.setattr(ragas_runner, "_score_with_ragas", fake_score)

    result = await ragas_runner.score_with_ragas([{"id": "sample"}])

    assert result == {"ragas_judged_samples": 1}
    assert checkpoint_root.is_dir()


def test_generation_workflow_lock_rejects_overlapping_process(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(ragas_runner, "CHECKPOINT_ROOT", tmp_path)

    with ragas_runner.generation_workflow_lock():
        with pytest.raises(RuntimeError, match="already running"):
            with ragas_runner.generation_workflow_lock():
                pass


def test_compatibility_marker_binds_answer_cache(monkeypatch, tmp_path) -> None:
    generator = SimpleNamespace(
        api_key="generator-key",
        api_base="https://generator.example.test",
        model="generator",
        thinking_mode=None,
    )
    judge = SimpleNamespace(
        api_key="judge-key",
        api_base="https://judge.example.test",
        model="judge",
        thinking_mode=None,
    )
    monkeypatch.setattr(ragas_runner, "CHECKPOINT_ROOT", tmp_path)
    monkeypatch.setattr(
        "evaluation.index_provenance.validate_evaluation_index",
        lambda: {"fingerprint": "index"},
    )
    monkeypatch.setattr(
        "evaluation.llm_factory.load_generator_llm_config", lambda: generator
    )
    monkeypatch.setattr("evaluation.llm_factory.load_judge_llm_config", lambda: judge)
    ragas_runner._record_compatibility_check(
        generator_live_probe=True,
        judge_live_requests=1,
        answer_cache_fingerprint="expected",
        metric_cache_proof={"sample_fingerprint": "sample", "successful_metrics": []},
    )

    ragas_runner.require_compatibility_answer_cache(tmp_path / "expected.json")
    with pytest.raises(RuntimeError, match="answer cache"):
        ragas_runner.require_compatibility_answer_cache(tmp_path / "other.json")


def test_truncated_ragas_checkpoint_requires_explicit_repair(tmp_path) -> None:
    path = tmp_path / "checkpoint.jsonl"
    path.write_text(
        '{"fingerprint":"fingerprint","sample_id":"one","metric":"faithfulness",'
        '"status":"success","value":1.0}\n{"fingerprint":',
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="unknown payment state"):
        ragas_runner._load_checkpoint(path, "fingerprint")
    records = ragas_runner._load_checkpoint(
        path,
        "fingerprint",
        repair_truncated_tail=True,
    )

    assert records[("one", "faithfulness")]["value"] == 1.0
    assert path.read_text(encoding="utf-8").endswith("\n")


def test_formal_ragas_requires_matching_compatibility_check(
    monkeypatch, tmp_path
) -> None:
    generator = SimpleNamespace(
        api_key="generator-key",
        api_base="https://generator.example.test",
        model="generator",
        thinking_mode=None,
    )
    judge = SimpleNamespace(
        api_key="judge-key",
        api_base="https://judge.example.test",
        model="judge",
        thinking_mode=None,
    )
    monkeypatch.setattr(ragas_runner, "CHECKPOINT_ROOT", tmp_path)
    monkeypatch.setattr(
        "evaluation.index_provenance.validate_evaluation_index",
        lambda: {"fingerprint": "index"},
    )
    monkeypatch.setattr(
        "evaluation.llm_factory.load_generator_llm_config", lambda: generator
    )
    monkeypatch.setattr("evaluation.llm_factory.load_judge_llm_config", lambda: judge)

    with pytest.raises(RuntimeError, match="compatibility check"):
        ragas_runner.require_compatibility_check()
    ragas_runner._record_compatibility_check(
        generator_live_probe=True,
        judge_live_requests=1,
        answer_cache_fingerprint="answer",
        metric_cache_proof={"sample_fingerprint": "sample", "successful_metrics": []},
    )
    ragas_runner.require_compatibility_check()
    ragas_runner.invalidate_compatibility_check()
    with pytest.raises(RuntimeError, match="compatibility check"):
        ragas_runner.require_compatibility_check()


@pytest.mark.asyncio
async def test_generation_answer_cache_reuses_paid_result(
    monkeypatch, tmp_path
) -> None:
    config = SimpleNamespace(
        api_base="https://example.test",
        model="generator",
        thinking_mode=None,
    )
    monkeypatch.setattr(ragas_runner, "ANSWER_CACHE_ROOT", tmp_path)
    monkeypatch.setattr(ragas_runner, "_generation_contract_sha256", lambda: "code")
    monkeypatch.setattr(
        "evaluation.llm_factory.load_generator_llm_config",
        lambda: config,
    )
    calls = 0

    async def generate() -> dict:
        nonlocal calls
        calls += 1
        return {"answer": "cached"}

    item = {
        "id": "sample",
        "request": {
            "prompt": "question with context",
            "deterministic_response": None,
        },
    }

    first, _path, first_hit = await ragas_runner.load_or_create_generation_answer(
        item, generate
    )
    second, _path, second_hit = await ragas_runner.load_or_create_generation_answer(
        item, generate
    )

    assert calls == 1
    assert first == second == {"answer": "cached"}
    assert first_hit is False
    assert second_hit is True


@pytest.mark.asyncio
async def test_generation_answer_unknown_payment_state_needs_explicit_retry(
    monkeypatch, tmp_path
) -> None:
    config = SimpleNamespace(
        api_base="https://example.test",
        model="generator",
        thinking_mode=None,
    )
    monkeypatch.setattr(ragas_runner, "ANSWER_CACHE_ROOT", tmp_path)
    monkeypatch.setattr(
        "evaluation.llm_factory.load_generator_llm_config", lambda: config
    )
    item = {
        "id": "sample",
        "request": {"prompt": "question", "deterministic_response": None},
    }
    _cached, path = ragas_runner.load_generation_answer(item)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.with_suffix(".inflight.json").write_text("{}", encoding="utf-8")
    calls = 0

    async def generate() -> dict:
        nonlocal calls
        calls += 1
        return {"answer": "retried"}

    with pytest.raises(RuntimeError, match="unknown payment state"):
        await ragas_runner.load_or_create_generation_answer(item, generate)
    result, _path, cache_hit = await ragas_runner.load_or_create_generation_answer(
        item,
        generate,
        retry_unknown_paid_calls=True,
    )

    assert calls == 1
    assert cache_hit is False
    assert result == {"answer": "retried"}


@pytest.mark.asyncio
async def test_ragas_check_metrics_are_reused_by_formal_batch(
    monkeypatch, tmp_path
) -> None:
    generator_config = SimpleNamespace(
        api_key="generator-key",
        api_base="https://example.test",
        model="generator",
        thinking_mode=None,
    )
    judge_config = SimpleNamespace(
        api_key="judge-key",
        api_base="https://judge.example.test",
        model="judge",
        thinking_mode=None,
    )
    usage = TokenUsage()

    class FakeJudge:
        llm = object()

        async def aclose(self) -> None:
            return None

    judge = FakeJudge()
    judge.usage = usage
    calls = 0

    class FakeMetric:
        async def ascore(self, **kwargs):
            nonlocal calls
            calls += 1
            usage.record({"usage": {}})
            return SimpleNamespace(value=1.0)

    monkeypatch.setattr(ragas_runner, "CHECKPOINT_ROOT", tmp_path)
    monkeypatch.setattr(
        "evaluation.index_provenance.validate_evaluation_index",
        lambda: {"fingerprint": "index"},
    )
    monkeypatch.setattr(
        "evaluation.llm_factory.load_generator_llm_config", lambda: generator_config
    )
    monkeypatch.setattr(
        "evaluation.llm_factory.load_judge_llm_config", lambda: judge_config
    )
    monkeypatch.setattr(
        "evaluation.llm_factory.build_ragas_judge", lambda **kwargs: judge
    )
    monkeypatch.setattr(
        "evaluation.llm_factory.build_ragas_embeddings", lambda: object()
    )
    monkeypatch.setattr(
        ragas_runner,
        "_metric_factories",
        lambda *_args: tuple((key, FakeMetric) for key in ragas_runner.METRIC_KEYS),
    )
    monkeypatch.setattr(
        ragas_runner,
        "_metric_kwargs",
        lambda _metric, item: {"item": item},
    )
    first = {
        "id": ragas_runner.formal_sample_manifest()["sample_ids"][0],
        "user_input": "question one",
        "response": "answer one",
        "retrieved_contexts": ["context one"],
        "reference": "answer one",
    }
    second = {
        "id": "second",
        "user_input": "question two",
        "response": "answer two",
        "retrieved_contexts": ["context two"],
        "reference": "answer two",
    }

    check = await ragas_runner._score_with_ragas([first], force_live=True)
    await ragas_runner._score_with_ragas([first], force_live=True)
    formal = await ragas_runner._score_with_ragas([first, second])

    assert check["ragas_completed_samples"] == 1
    assert formal["ragas_completed_samples"] == 2
    assert calls == len(ragas_runner.METRIC_KEYS) * 3


@pytest.mark.asyncio
async def test_ragas_failure_cancels_and_joins_other_judge_tasks(
    monkeypatch, tmp_path
) -> None:
    config = SimpleNamespace(
        api_key="key",
        api_base="https://example.test",
        model="generator",
        thinking_mode=None,
    )
    judge_config = SimpleNamespace(**{**vars(config), "model": "judge"})
    second_started = asyncio.Event()
    second_cancelled = asyncio.Event()

    class FakeJudge:
        llm = object()
        usage = TokenUsage()
        closed = False

        async def aclose(self) -> None:
            self.closed = True

    judge = FakeJudge()

    class FakeMetric:
        async def ascore(self, *, item):
            if item["id"] == "first":
                await second_started.wait()
                raise RuntimeError("provider failed")
            second_started.set()
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                second_cancelled.set()
                raise

    monkeypatch.setenv("EVAL_JUDGE_CONCURRENCY", "2")
    monkeypatch.setattr(ragas_runner, "CHECKPOINT_ROOT", tmp_path)
    monkeypatch.setattr(
        "evaluation.llm_factory.load_generator_llm_config", lambda: config
    )
    monkeypatch.setattr(
        "evaluation.llm_factory.load_judge_llm_config", lambda: judge_config
    )
    monkeypatch.setattr(
        "evaluation.llm_factory.build_ragas_judge", lambda **_kwargs: judge
    )
    monkeypatch.setattr(
        "evaluation.llm_factory.build_ragas_embeddings", lambda: object()
    )
    monkeypatch.setattr(
        ragas_runner,
        "_metric_factories",
        lambda *_args: (("faithfulness", FakeMetric),),
    )
    monkeypatch.setattr(
        ragas_runner,
        "_metric_kwargs",
        lambda _metric, item: {"item": item},
    )

    with pytest.raises(RuntimeError, match="unknown payment state"):
        await ragas_runner._score_with_ragas(
            [
                {
                    "id": "first",
                    "user_input": "question one",
                    "response": "answer one",
                    "retrieved_contexts": ["context one"],
                    "reference": "answer one",
                },
                {
                    "id": "second",
                    "user_input": "question two",
                    "response": "answer two",
                    "retrieved_contexts": ["context two"],
                    "reference": "answer two",
                },
            ],
            force_live=True,
        )

    assert second_cancelled.is_set()
    assert judge.closed is True


class _Chunk:
    def __init__(self, content: str, output_tokens: int | None = None) -> None:
        self.content = content
        self.usage_metadata = (
            {"output_tokens": output_tokens} if output_tokens is not None else None
        )
        self.response_metadata = {}


class _StreamingLLM:
    async def astream(self, _prompt: str):
        yield _Chunk("")
        yield _Chunk("答")
        await asyncio.sleep(0)
        yield _Chunk("案", output_tokens=3)


class _EmptyStreamingLLM:
    async def astream(self, _prompt: str):
        yield _Chunk("")


def test_stream_measurement_uses_api_token_count() -> None:
    result = asyncio.run(_measure_stream(_StreamingLLM(), "question"))

    assert result.answer == "答案"
    assert result.output_tokens == 3
    assert result.token_count_source == "api_usage"
    assert result.ttft_ms is not None
    assert result.tpot_ms is not None
    assert len(result.chunk_gaps_ms) == 1
    assert result.fallback is False


def test_empty_stream_is_not_a_successful_live_generation() -> None:
    result = asyncio.run(_measure_stream(_EmptyStreamingLLM(), "question"))

    assert result.answer == ""
    assert _is_successful_live_generation(result) is False


def test_report_renders_nested_metric_counts() -> None:
    lines = _render_metric_table(
        "Generation",
        {"ragas_metric_valid_samples": {"faithfulness": 12}},
    )

    assert "### ragas_metric_valid_samples" in lines
    assert "| faithfulness | 12 |" in lines


def test_threshold_metrics_penalize_wrong_and_unanswerable_emissions() -> None:
    records = [
        {
            "split": "calibration",
            "expected": True,
            "chunks": [
                {"score": 0.95, "relevant": True},
                {"score": 0.7, "relevant": False},
            ],
        },
        {
            "split": "calibration",
            "expected": False,
            "chunks": [{"score": 0.75, "relevant": False}],
        },
    ]

    strict = _threshold_metrics(records, 0.8)
    permissive = _threshold_metrics(records, 0.7)

    assert strict["precision"] == 1.0
    assert strict["negative_false_positive_rate"] == 0.0
    assert permissive["precision"] == 0.5
    assert permissive["negative_false_positive_rate"] == 1.0


def test_multi_intent_threshold_metrics_match_production_margin_policy() -> None:
    chunks = [
        {"score": 0.95, "relevant": False},
        {"score": 0.90, "relevant": True},
    ]

    single_intent = _threshold_metrics(
        [{"expected": True, "allow_margin": True, "chunks": chunks}],
        threshold=0.8,
        score_margin=0.01,
    )
    multi_intent = _threshold_metrics(
        [{"expected": True, "allow_margin": False, "chunks": chunks}],
        threshold=0.8,
        score_margin=0.01,
    )

    assert single_intent["recall"] == 0.0
    assert multi_intent["recall"] == 1.0


def test_calibration_never_uses_held_out_rows_to_select_threshold() -> None:
    records = [
        {
            "split": "calibration",
            "expected": True,
            "chunks": [
                {
                    "score": 0.91,
                    "relevant": True,
                    "source_match": True,
                    "document_id": "doc-a",
                    "text": "exact evidence term",
                }
            ],
            "gold_chunk_count": 1,
            "expected_document_ids": ["doc-a"],
            "reference_terms": ["exact evidence"],
            "source_format": "html",
            "language": "en",
        },
        {
            "split": "calibration",
            "expected": False,
            "chunks": [
                {
                    "score": 0.89,
                    "relevant": False,
                    "source_match": False,
                    "document_id": "doc-b",
                    "text": "unrelated",
                }
            ],
            "source_format": "html",
            "language": "en",
        },
        {
            "split": "test",
            "expected": True,
            "chunks": [
                {
                    "score": 0.55,
                    "relevant": True,
                    "source_match": True,
                    "document_id": "doc-a",
                    "text": "exact evidence term",
                }
            ],
            "gold_chunk_count": 1,
            "expected_document_ids": ["doc-a"],
            "reference_terms": ["exact evidence"],
            "source_format": "html",
            "language": "en",
        },
    ]

    result = _calibrate_threshold(records)

    assert result["recommended_threshold"] == 0.91
    assert result["calibration_metrics"]["recall"] == 1.0
    assert result["held_out_test_metrics"]["recall"] == 0.0


def test_calibration_does_not_recommend_from_an_empty_split() -> None:
    result = _calibrate_threshold(
        [
            {
                "split": "test",
                "expected": True,
                "chunks": [{"score": 0.99, "relevant": True}],
            }
        ]
    )

    assert result["calibration_samples"] == 0
    assert result["test_samples"] == 1
    assert result["recommended_threshold"] is None
    assert result["sweep"] == []


def test_binary_ranking_metrics_reward_score_separation() -> None:
    result = _binary_ranking_metrics(
        [(0.95, True), (0.85, True), (0.2, False), (0.1, False)]
    )

    assert result == {"auroc": 1.0, "average_precision": 1.0}
