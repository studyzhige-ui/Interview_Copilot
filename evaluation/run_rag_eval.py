import asyncio
import json
import math
import os
import shutil
import statistics
import time
from pathlib import Path
from typing import Any

from datasets import Dataset
from langchain_openai import ChatOpenAI
from openai import OpenAI
from ragas import evaluate
from ragas.llms import llm_factory
from ragas.run_config import RunConfig


import sys
from pathlib import Path

# Resolve the repository root.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Add backend/ to the Python import path.
sys.path.append(str(PROJECT_ROOT / "backend"))

from app.core.hf_runtime import prepare_hf_runtime
from app.core.config import settings
from app.rag.ingestion import ingest_document
from app.rag.retriever import query_knowledge_base
from ragas.metrics import _Faithfulness, _LLMContextPrecisionWithReference, _LLMContextRecall


prepare_hf_runtime()


# 所有的路径现在都基于 settings.EVAL_DIR
EVAL_DIR = Path(settings.EVAL_DIR)
UPLOAD_DIR = EVAL_DIR / "source_files"  # 评估用的 PDF 源文件
DATASET_PATH = EVAL_DIR / "eval_dataset.jsonl"
CHROMA_DIR = Path(settings.CHROMA_DB_DIR)
DOCSTORE_DIR = Path(settings.DOCSTORE_DIR)

EVAL_USER_ID = "eval_user"
EVAL_CONCURRENCY = int(os.getenv("EVAL_CONCURRENCY", "4"))
RELEVANCE_THRESHOLD = float(os.getenv("EVAL_RELEVANCE_THRESHOLD", "0.15"))
TIMEOUT_SECONDS = float(os.getenv("EVAL_TIMEOUT_SECONDS", "60"))
RAGAS_CHUNK_SIZE = int(os.getenv("RAGAS_CHUNK_SIZE", "10"))
RAGAS_MAX_WORKERS = int(os.getenv("RAGAS_MAX_WORKERS", "32"))
EVAL_MIN_SCORE = float(os.getenv("EVAL_MIN_SCORE", str(settings.RAG_MIN_SCORE)))


def score_tag(value: float) -> str:
    return str(value).replace(".", "_")


SCORE_TAG = score_tag(EVAL_MIN_SCORE)
RESULT_PATH = EVAL_DIR / f"eval_results_min_score_{SCORE_TAG}.json"
DETAIL_PATH = EVAL_DIR / f"eval_details_min_score_{SCORE_TAG}.json"
RAW_RESULT_PATH = EVAL_DIR / f"eval_generation_cache_min_score_{SCORE_TAG}.json"
RAGAS_CACHE_PATH = EVAL_DIR / f"eval_ragas_cache_min_score_{SCORE_TAG}.json"


def normalize(text: str) -> str:
    return " ".join(text.replace("\n", " ").split()).strip().lower()


def overlap_score(a: str, b: str) -> float:
    a_tokens = set(normalize(a).split())
    b_tokens = set(normalize(b).split())
    if not a_tokens or not b_tokens:
        return 0.0
    return len(a_tokens & b_tokens) / len(a_tokens)


def dcg(scores: list[float]) -> float:
    value = 0.0
    for rank, score in enumerate(scores, start=1):
        gain = max(score, 0.0)
        if gain == 0.0:
            continue
        value += gain / math.log2(rank + 1)
    return value


def load_dataset(limit: int | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with DATASET_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            rows.append(json.loads(line))
    if limit:
        return rows[:limit]
    return rows


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    idx = (len(ordered) - 1) * p
    lower = int(idx)
    upper = min(lower + 1, len(ordered) - 1)
    weight = idx - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


async def rebuild_index() -> float:
    started = time.perf_counter()
    shutil.rmtree(CHROMA_DIR, ignore_errors=True)
    shutil.rmtree(DOCSTORE_DIR, ignore_errors=True)
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    DOCSTORE_DIR.mkdir(parents=True, exist_ok=True)
    from app.rag import ingestion as ingestion_module
    from app.rag import retriever as retriever_module

    ingestion_module.CHROMA_DB_DIR = str(CHROMA_DIR)
    ingestion_module.DOCSTORE_DIR = str(DOCSTORE_DIR)
    retriever_module.CHROMA_DB_DIR = str(CHROMA_DIR)
    retriever_module.DOCSTORE_DIR = str(DOCSTORE_DIR)
    for pdf_path in sorted(UPLOAD_DIR.glob("*.pdf")):
        await ingest_document(str(pdf_path), "interview_qa", user_id=EVAL_USER_ID)
    return round((time.perf_counter() - started) * 1000, 2)


async def answer_with_rag(question: str) -> dict[str, Any]:
    started = time.perf_counter()
    retrieval = await query_knowledge_base(
        query_str=question,
        user_id=EVAL_USER_ID,
        source_type="interview_qa",
        min_score=EVAL_MIN_SCORE,
    )
    retrieval_elapsed = time.perf_counter() - started

    contexts = [source.get("text", "") for source in retrieval.get("sources", [])]
    scores = [
        float(source.get("score", 0.0))
        for source in retrieval.get("sources", [])
        if source.get("score") is not None
    ]
    context_block = "\n\n".join(contexts[:3])

    llm = ChatOpenAI(
        model="deepseek-chat",
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url="https://api.deepseek.com",
        temperature=0,
    )
    prompt = (
        "你是面试问答助手。请严格基于给定参考资料回答问题；"
        "如果资料不足，明确说资料不足，不要编造。\n\n"
        f"问题：{question}\n\n"
        f"参考资料：\n{context_block}"
    )
    llm_started = time.perf_counter()
    response = await llm.ainvoke(prompt)
    generation_elapsed = time.perf_counter() - llm_started
    total_elapsed = time.perf_counter() - started
    usage = getattr(response, "usage_metadata", None) or {}
    prompt_tokens = usage.get("input_tokens")
    completion_tokens = usage.get("output_tokens")
    total_tokens = usage.get("total_tokens")
    return {
        "answer": response.content if isinstance(response.content, str) else str(response.content),
        "contexts": contexts,
        "scores": scores,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "retrieval_latency_ms": round(retrieval_elapsed * 1000, 2),
        "generation_latency_ms": round(generation_elapsed * 1000, 2),
        "total_latency_ms": round(total_elapsed * 1000, 2),
    }


async def process_row(
    idx: int,
    total: int,
    row: dict[str, Any],
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    async with semaphore:
        status = "ok"
        error_message = None
        timeout = False
        try:
            result = await asyncio.wait_for(answer_with_rag(row["question"]), timeout=TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            timeout = True
            status = "timeout"
            error_message = f"generation timed out after {TIMEOUT_SECONDS:.0f}s"
            result = {
                "answer": "",
                "contexts": [],
                "scores": [],
                "prompt_tokens": None,
                "completion_tokens": None,
                "total_tokens": None,
                "retrieval_latency_ms": round(TIMEOUT_SECONDS * 1000, 2),
                "generation_latency_ms": 0.0,
                "total_latency_ms": round(TIMEOUT_SECONDS * 1000, 2),
            }
        except Exception as exc:
            status = "error"
            error_message = str(exc)
            result = {
                "answer": "",
                "contexts": [],
                "scores": [],
                "prompt_tokens": None,
                "completion_tokens": None,
                "total_tokens": None,
                "retrieval_latency_ms": 0.0,
                "generation_latency_ms": 0.0,
                "total_latency_ms": 0.0,
            }

        contexts = result["contexts"]
        scores = result["scores"]

        ranked_scores = [overlap_score(row["reference"], context) for context in contexts[:3]]
        binary_relevances = [1 if score >= RELEVANCE_THRESHOLD else 0 for score in ranked_scores]
        positives = sum(binary_relevances)
        reference_positive = 1
        hit = int(positives > 0)
        precision_at_3 = positives / 3 if contexts else 0.0
        recall_at_3 = positives / reference_positive if reference_positive else 0.0
        ndcg_at_3 = 0.0
        if ranked_scores:
            ideal_scores = sorted(ranked_scores, reverse=True)
            ideal_dcg = dcg(ideal_scores)
            ndcg_at_3 = dcg(ranked_scores) / ideal_dcg if ideal_dcg > 0 else 0.0

        rr = 0.0
        for rank, score in enumerate(ranked_scores, start=1):
            if score >= RELEVANCE_THRESHOLD:
                rr = 1.0 / rank
                break

        print(
            f"[{idx}/{total}] {row['question'][:50]} -> "
            f"contexts={len(contexts[:3])}, hit={hit}, status={status}"
        )

        return {
            "hit": hit,
            "rr": rr,
            "precision_at_3": precision_at_3,
            "recall_at_3": recall_at_3,
            "ndcg_at_3": ndcg_at_3,
            "status": status,
            "timeout": timeout,
            "detail": {
                "id": row["id"],
                "question": row["question"],
                "source_file": row["source_file"],
                "status": status,
                "error_message": error_message,
                "reference_chars": len(row["reference"]),
                "answer_chars": len(result["answer"]),
                "contexts_count": len(contexts[:3]),
                "no_answer": int(not result["answer"].strip()),
                "empty_contexts": int(len(contexts[:3]) == 0),
                "top1_source_score": round(scores[0], 4) if scores else None,
                "avg_source_score": round(statistics.mean(scores), 4) if scores else None,
                "prompt_tokens": result["prompt_tokens"],
                "completion_tokens": result["completion_tokens"],
                "total_tokens": result["total_tokens"],
                "retrieval_latency_ms": result["retrieval_latency_ms"],
                "generation_latency_ms": result["generation_latency_ms"],
                "total_latency_ms": result["total_latency_ms"],
                "hit_at_3": hit,
                "precision_at_3": round(precision_at_3, 4),
                "recall_at_3": round(recall_at_3, 4),
                "ndcg_at_3": round(ndcg_at_3, 4),
                "rr_at_3": rr,
            },
            "ragas_row": {
                "row_id": row["id"],
                "user_input": row["question"],
                "response": result["answer"],
                "retrieved_contexts": contexts[:3],
                "reference": row["reference"],
            },
        }


async def run_eval(limit: int | None = None) -> dict[str, Any]:
    eval_started = time.perf_counter()
    rows = load_dataset(limit=limit)
    use_cache = RAW_RESULT_PATH.exists()
    index_build_time_ms = None

    if not use_cache:
        index_build_time_ms = await rebuild_index()

    retrieval_hits_at_3: list[int] = []
    reciprocal_ranks: list[float] = []
    precisions_at_3: list[float] = []
    recalls_at_3: list[float] = []
    ndcgs_at_3: list[float] = []
    ragas_rows: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []
    if use_cache:
        results = json.loads(RAW_RESULT_PATH.read_text(encoding="utf-8"))
        if len(results) != len(rows):
            RAW_RESULT_PATH.unlink()
            index_build_time_ms = await rebuild_index()
            semaphore = asyncio.Semaphore(EVAL_CONCURRENCY)
            tasks = [
                process_row(idx, len(rows), row, semaphore)
                for idx, row in enumerate(rows, start=1)
            ]
            results = await asyncio.gather(*tasks)
            RAW_RESULT_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        semaphore = asyncio.Semaphore(EVAL_CONCURRENCY)
        tasks = [
            process_row(idx, len(rows), row, semaphore)
            for idx, row in enumerate(rows, start=1)
        ]
        results = await asyncio.gather(*tasks)
        RAW_RESULT_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    for item in results:
        retrieval_hits_at_3.append(item["hit"])
        reciprocal_ranks.append(item["rr"])
        precisions_at_3.append(item["precision_at_3"])
        recalls_at_3.append(item["recall_at_3"])
        ndcgs_at_3.append(item["ndcg_at_3"])
        details.append(item["detail"])
        if item["status"] == "ok":
            ragas_rows.append(item["ragas_row"])

    ragas_records_by_id: dict[str, dict[str, Any]] = {}
    if RAGAS_CACHE_PATH.exists():
        ragas_records_by_id = json.loads(RAGAS_CACHE_PATH.read_text(encoding="utf-8"))

    if ragas_rows:
        ragas_client = OpenAI(
            api_key=os.environ["DEEPSEEK_API_KEY"],
            base_url="https://api.deepseek.com",
        )
        ragas_llm = llm_factory(
            "deepseek-chat",
            client=ragas_client,
            temperature=0,
            max_tokens=8192,
        )
        metrics = [
            _Faithfulness(llm=ragas_llm),
            _LLMContextPrecisionWithReference(llm=ragas_llm),
            _LLMContextRecall(llm=ragas_llm),
        ]
        pending_rows = [
            row for row in ragas_rows
            if row["row_id"] not in ragas_records_by_id
        ]

        for start in range(0, len(pending_rows), RAGAS_CHUNK_SIZE):
            chunk_rows = pending_rows[start:start + RAGAS_CHUNK_SIZE]
            if not chunk_rows:
                continue
            chunk_dataset = Dataset.from_list([
                {
                    "user_input": row["user_input"],
                    "response": row["response"],
                    "retrieved_contexts": row["retrieved_contexts"],
                    "reference": row["reference"],
                }
                for row in chunk_rows
            ])
            ragas_result = evaluate(
                dataset=chunk_dataset,
                metrics=metrics,
                run_config=RunConfig(max_workers=RAGAS_MAX_WORKERS),
                batch_size=RAGAS_CHUNK_SIZE,
            )
            chunk_records = ragas_result.to_pandas().to_dict(orient="records")
            for row, record in zip(chunk_rows, chunk_records):
                ragas_records_by_id[row["row_id"]] = {
                    key: (float(value) if value == value else None)
                    for key, value in record.items()
                    if key in {"faithfulness", "llm_context_precision_with_reference", "context_recall"}
                }
            RAGAS_CACHE_PATH.write_text(
                json.dumps(ragas_records_by_id, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        ragas_records = [
            ragas_records_by_id[row["row_id"]]
            for row in ragas_rows
            if row["row_id"] in ragas_records_by_id
        ]
        ragas_summary = {}
        for metric_name in ["faithfulness", "llm_context_precision_with_reference", "context_recall"]:
            values = [item[metric_name] for item in ragas_records if item.get(metric_name) is not None]
            ragas_summary[metric_name] = statistics.mean(values) if values else 0.0
    else:
        ragas_summary = {}
        ragas_records = []

    retrieval_latencies = [item["retrieval_latency_ms"] for item in details]
    generation_latencies = [item["generation_latency_ms"] for item in details]
    total_latencies = [item["total_latency_ms"] for item in details]
    context_counts = [item["contexts_count"] for item in details]
    top1_scores = [item["top1_source_score"] for item in details if item["top1_source_score"] is not None]
    prompt_tokens = [item["prompt_tokens"] for item in details if item["prompt_tokens"] is not None]
    completion_tokens = [item["completion_tokens"] for item in details if item["completion_tokens"] is not None]
    total_tokens = [item["total_tokens"] for item in details if item["total_tokens"] is not None]
    failed_count = sum(1 for item in results if item["status"] != "ok")
    timeout_count = sum(1 for item in results if item["timeout"])
    no_answer_count = sum(item["no_answer"] for item in details)
    empty_context_count = sum(item["empty_contexts"] for item in details)
    low_confidence_count = sum(
        1
        for item in details
        if item["top1_source_score"] is None or item["top1_source_score"] < settings.RAG_MIN_SCORE
    )
    throughput = len(rows) / max(time.perf_counter() - eval_started, 1e-6)

    ragas_iter = iter(ragas_records)
    for detail in details:
        if detail["status"] != "ok":
            detail["ragas"] = None
            continue
        ragas_item = next(ragas_iter)
        detail["ragas"] = {
            key: (round(float(value), 4) if value == value else None)
            for key, value in ragas_item.items()
            if key in {"faithfulness", "llm_context_precision_with_reference", "context_recall"}
        }

    output = {
        "samples": len(rows),
        "concurrency": EVAL_CONCURRENCY,
        "relevance_threshold": RELEVANCE_THRESHOLD,
        "min_score": EVAL_MIN_SCORE,
        "storage": {
            "chroma_db_dir": str(CHROMA_DIR),
            "docstore_dir": str(DOCSTORE_DIR),
        },
        "index_build_time_ms": index_build_time_ms,
        "throughput_qps": round(throughput, 4),
        "retrieval": {
            "hit_rate_at_3": round(sum(retrieval_hits_at_3) / len(retrieval_hits_at_3), 4),
            "mrr_at_3": round(sum(reciprocal_ranks) / len(reciprocal_ranks), 4),
            "precision_at_3": round(sum(precisions_at_3) / len(precisions_at_3), 4),
            "recall_at_3": round(sum(recalls_at_3) / len(recalls_at_3), 4),
            "ndcg_at_3": round(sum(ndcgs_at_3) / len(ndcgs_at_3), 4),
            "avg_contexts": round(statistics.mean(context_counts), 2),
            "avg_top1_score": round(statistics.mean(top1_scores), 4) if top1_scores else None,
        },
        "reliability": {
            "failure_rate": round(failed_count / len(rows), 4),
            "timeout_rate": round(timeout_count / len(rows), 4),
            "no_answer_rate": round(no_answer_count / len(rows), 4),
            "empty_context_rate": round(empty_context_count / len(rows), 4),
            "low_confidence_rate": round(low_confidence_count / len(rows), 4),
        },
        "tokens": {
            "prompt_total": int(sum(prompt_tokens)) if prompt_tokens else 0,
            "completion_total": int(sum(completion_tokens)) if completion_tokens else 0,
            "all_total": int(sum(total_tokens)) if total_tokens else 0,
            "prompt_avg": round(statistics.mean(prompt_tokens), 2) if prompt_tokens else 0.0,
            "completion_avg": round(statistics.mean(completion_tokens), 2) if completion_tokens else 0.0,
            "all_avg": round(statistics.mean(total_tokens), 2) if total_tokens else 0.0,
        },
        "latency_ms": {
            "retrieval_avg": round(statistics.mean(retrieval_latencies), 2),
            "retrieval_p50": round(percentile(retrieval_latencies, 0.5), 2),
            "retrieval_p95": round(percentile(retrieval_latencies, 0.95), 2),
            "generation_avg": round(statistics.mean(generation_latencies), 2),
            "generation_p50": round(percentile(generation_latencies, 0.5), 2),
            "generation_p95": round(percentile(generation_latencies, 0.95), 2),
            "end_to_end_avg": round(statistics.mean(total_latencies), 2),
            "end_to_end_p50": round(percentile(total_latencies, 0.5), 2),
            "end_to_end_p95": round(percentile(total_latencies, 0.95), 2),
        },
        "ragas": {k: round(v, 4) for k, v in ragas_summary.items()},
        "ragas_progress": {
            "completed": len(ragas_records),
            "total": len(ragas_rows),
            "cache_path": str(RAGAS_CACHE_PATH),
        },
        "details_path": str(DETAIL_PATH),
    }
    DETAIL_PATH.write_text(json.dumps(details, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def main() -> None:
    limit = int(os.getenv("EVAL_LIMIT", "200"))
    if os.getenv("EVAL_FORCE_REBUILD", "0") == "1":
        if RAW_RESULT_PATH.exists():
            RAW_RESULT_PATH.unlink()
        if RAGAS_CACHE_PATH.exists():
            RAGAS_CACHE_PATH.unlink()
    result = asyncio.run(run_eval(limit=limit))
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
