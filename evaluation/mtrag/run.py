"""Full-corpus local retrieval campaign; no network or LLM calls in this runner."""

import argparse
import gc
import json
import math
import re
import time
from collections import Counter
from pathlib import Path

from .local_models import LocalModel, np, torch
from scipy import sparse

from .download import ROOT
from .prepare import DOMAINS
from .profile import fingerprint, load_profile
from .rewrite import atomic_json, cache_identity

ANALYZER = "lowercase-ascii-alphanumeric-v1-no-stemming-no-stopwords"


def read_rows(path):
    with Path(path).open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def token_terms(text):
    return re.findall(r"[a-z0-9]+", text.lower())


def topk(scores, k=50, *, positive=False):
    # A stable full sort also specifies deterministic ties by corpus position.
    order = np.argsort(-scores, kind="stable")[:k]
    return order[scores[order] > 0] if positive else order


class BM25:
    def __init__(self, rows, *, k1=1.2, b=0.75):
        vocabulary, columns, values, indptr, lengths = {}, [], [], [0], []
        for row in rows:
            counts = Counter(token_terms(row["text"]))
            lengths.append(sum(counts.values()))
            for term, count in counts.items():
                if term not in vocabulary:
                    vocabulary[term] = len(vocabulary)
                columns.append(vocabulary[term])
                values.append(count)
            indptr.append(len(columns))
        matrix = sparse.csr_matrix(
            (
                np.asarray(values, dtype="float32"),
                np.asarray(columns),
                np.asarray(indptr),
            ),
            shape=(len(rows), len(vocabulary)),
        )
        lengths = np.asarray(lengths, dtype="float32")
        norm = k1 * (1 - b + b * lengths / max(float(lengths.mean()), 1))
        df = np.bincount(matrix.indices, minlength=len(vocabulary))
        idf = np.log1p((len(rows) - df + 0.5) / (df + 0.5))
        matrix.data = (
            (matrix.data * (k1 + 1))
            / (matrix.data + np.repeat(norm, np.diff(matrix.indptr)))
            * idf[matrix.indices]
        ).astype("float32")
        self.matrix, self.vocabulary = matrix.tocsc(), vocabulary

    def search(self, query):
        columns = [
            self.vocabulary[term]
            for term in set(token_terms(query))
            if term in self.vocabulary
        ]
        return np.asarray(self.matrix[:, columns].sum(axis=1)).ravel()


def fusion(first, second, k=50, rrf_k=60):
    scores = {}
    for ranking in (first, second):
        for rank, pid in enumerate(ranking, 1):
            scores[pid] = scores.get(pid, 0.0) + 1 / (rrf_k + rank)
    pairs = sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:k]
    return [pair[0] for pair in pairs], [pair[1] for pair in pairs]


def score_ranking(ids, qrels):
    relevant = {pid for pid, gain in qrels.items() if gain > 0}
    if not relevant:
        raise ValueError("No-positive queries are excluded before evaluation")
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate result IDs would inflate recall")
    metrics = {"recall@50": len(set(ids[:50]) & relevant) / len(relevant)}
    for k in (5, 10):
        hits = len(set(ids[:k]) & relevant)
        gains = [qrels.get(pid, 0) for pid in ids[:k]]
        ideal = sorted(qrels.values(), reverse=True)[:k]
        dcg = sum(
            (2**gain - 1) / math.log2(rank + 2) for rank, gain in enumerate(gains)
        )
        idcg = sum(
            (2**gain - 1) / math.log2(rank + 2) for rank, gain in enumerate(ideal)
        )
        metrics.update(
            {
                f"recall@{k}": hits / len(relevant),
                f"hit@{k}": float(hits > 0),
                f"ndcg@{k}": dcg / idcg,
            }
        )
    return metrics


def queries(profile, rewritten_path=None):
    originals = {r["query_id"]: r for r in read_rows(ROOT / "queries.jsonl")}
    rewritten_rows = read_rows(rewritten_path or ROOT / "rewritten.jsonl")
    rewritten = {r["query_id"]: r for r in rewritten_rows}
    if len(rewritten) != len(rewritten_rows) or rewritten.keys() != originals.keys():
        raise ValueError("Rewrite IDs must cover the input exactly once")
    output = []
    for task in read_rows(ROOT / "tasks.jsonl"):
        qid = task["query_id"]
        expected = cache_identity(originals[qid], profile)[1]
        if rewritten[qid]["request_sha256"] != expected:
            raise ValueError(f"Stale rewrite for {qid}")
        for mode in profile["query_modes"]:
            query = (
                task["last_turn"] if mode == "last_turn" else rewritten[qid]["query"]
            )
            output.append(
                {**task, "mode": mode, "query": query, "key": f"{mode}::{qid}"}
            )
    return output


class Results:
    def __init__(self, name, identity, directory=None):
        directory = directory or ROOT / "runs"
        directory.mkdir(exist_ok=True)
        self.path = directory / f"{name}.jsonl"
        meta = directory / f"{name}.meta.json"
        if meta.exists():
            if json.loads(meta.read_text(encoding="utf-8"))["identity"] != identity:
                raise ValueError(f"Changed campaign identity for {name}")
        else:
            if self.path.exists():
                raise ValueError("Results without metadata")
            atomic_json(meta, {"identity": identity})
        self.rows = (
            {r["key"]: r for r in read_rows(self.path)} if self.path.exists() else {}
        )

    def save(self, task, ids, scores, timings, **extra):
        row = {
            "key": task["key"],
            "query_id": task["query_id"],
            "dataset": task["dataset"],
            "domain": task["domain"],
            "mode": task["mode"],
            "ids": ids,
            "scores": scores,
            "top10_ids": ids[:10],
            "metrics": score_ranking(ids, task["qrels"]),
            "timings_ms": timings,
            **extra,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
        self.rows[row["key"]] = row


def corpus(domain):
    return read_rows(ROOT / "corpus" / f"{domain}.jsonl")


def campaign_identity(profile):
    return fingerprint(
        {
            "profile": profile,
            "analyzer": ANALYZER,
            "audit": json.loads((ROOT / "data_audit.json").read_text(encoding="utf-8")),
            "rewrites": [
                {key: row[key] for key in ("query_id", "query", "request_sha256")}
                for row in read_rows(ROOT / "rewritten.jsonl")
            ],
            "runtime": json.loads(
                (ROOT / "runtime_manifest.json").read_text(encoding="utf-8")
            ),
            "runner_version": "v1",
        }
    )


def lexical(profile, tasks, identity, run_directory=None):
    run_directory = run_directory or ROOT / "runs"
    results = Results("bm25", identity, run_directory)
    for domain in DOMAINS:
        pending = [
            q for q in tasks if q["domain"] == domain and q["key"] not in results.rows
        ]
        if not pending:
            continue
        rows = corpus(domain)
        started = time.perf_counter()
        model = BM25(
            rows, k1=profile["retrieval"]["bm25_k1"], b=profile["retrieval"]["bm25_b"]
        )
        atomic_json(
            run_directory / f"bm25-index-{domain}.json",
            {
                "seconds": time.perf_counter() - started,
                "analyzer": ANALYZER,
                "passages": len(rows),
                "terms": len(model.vocabulary),
            },
        )
        model.search("warm up the keyword retrieval")
        for index, task in enumerate(pending, 1):
            started = time.perf_counter()
            scores = model.search(task["query"])
            order = topk(scores, profile["retrieval"]["per_channel_k"], positive=True)
            elapsed = (time.perf_counter() - started) * 1000
            results.save(
                task,
                [rows[i]["_id"] for i in order],
                scores[order].tolist(),
                {"bm25": elapsed, "total": elapsed},
            )
            if index % 50 == 0:
                print("bm25", domain, index, "/", len(pending), flush=True)
        del model, rows
        gc.collect()


def dense(profile, tasks, identity, family, run_directory=None):
    run_directory = run_directory or ROOT / "runs"
    results = Results(f"{family}_dense", identity, run_directory)
    hybrid = Results(f"bm25_{family}", identity, run_directory)
    bm25 = {r["key"]: r for r in read_rows(run_directory / "bm25.jsonl")}
    model = LocalModel(family, "embedding", profile)
    model.embed(["warm up query"], query=True)
    model.truncation = {"items": 0, "truncated": 0, "query_truncated": 0}
    torch.backends.cuda.matmul.allow_tf32 = False
    for domain in DOMAINS:
        metadata = json.loads(
            (ROOT / "vectors" / family / f"{domain}.meta.json").read_text(
                encoding="utf-8"
            )
        )
        if not metadata["complete"]:
            raise ValueError(f"Incomplete vector index {family}/{domain}")
        rows = corpus(domain)
        empty = np.asarray([not row["text"].strip() for row in rows])
        array = np.load(ROOT / "vectors" / family / f"{domain}.npy")
        expected_shape = (
            len(rows),
            profile["models"][f"{family}_embedding"]["dimensions"],
        )
        if array.shape != expected_shape or not np.isfinite(array).all():
            raise ValueError(f"Invalid vector array {family}/{domain}")
        norms = np.linalg.norm(array, axis=1)
        if not np.allclose(norms[~empty], 1, atol=1e-4) or not np.all(
            norms[empty] == 0
        ):
            raise ValueError(f"Invalid normalized vectors {family}/{domain}")
        sample = [
            int(i) for i in np.linspace(0, len(rows) - 1, 5, dtype=int) if not empty[i]
        ]
        previous_truncation = dict(model.truncation)
        reference = model.embed([rows[i]["text"] for i in sample])
        model.truncation = previous_truncation
        cosines = np.einsum("ij,ij->i", array[sample], reference)
        if not np.all(cosines > 0.999):
            raise ValueError(
                f"Vector/ID alignment check failed {family}/{domain}: {cosines}"
            )
        atomic_json(
            run_directory / f"vector-validation-{family}-{domain}.json",
            {
                "finite": True,
                "normalized": True,
                "shape": list(array.shape),
                "sample_ids": [rows[i]["_id"] for i in sample],
                "sample_cosines": cosines.tolist(),
            },
        )
        vectors = torch.from_numpy(array).to("cuda")
        del array, norms
        domain_tasks = [q for q in tasks if q["domain"] == domain]
        for index, task in enumerate(domain_tasks, 1):
            if task["key"] not in results.rows:
                torch.cuda.synchronize()
                started = time.perf_counter()
                query_vector = torch.from_numpy(
                    model.embed([task["query"]], query=True)
                ).to("cuda")
                torch.cuda.synchronize()
                embed_ms = (time.perf_counter() - started) * 1000
                search_start = time.perf_counter()
                scores = (vectors @ query_vector[0]).cpu().numpy()
                scores[empty] = -np.inf
                order = topk(scores, profile["retrieval"]["per_channel_k"])
                search_ms = (time.perf_counter() - search_start) * 1000
                results.save(
                    task,
                    [rows[i]["_id"] for i in order],
                    scores[order].tolist(),
                    {
                        "query_embedding": embed_ms,
                        "dense_search": search_ms,
                        "total": embed_ms + search_ms,
                    },
                )
            if task["key"] not in hybrid.rows:
                first, second = bm25[task["key"]], results.rows[task["key"]]
                started = time.perf_counter()
                ids, scores = fusion(
                    first["ids"],
                    second["ids"],
                    profile["retrieval"]["fused_k"],
                    profile["retrieval"]["rrf_k"],
                )
                fusion_ms = (time.perf_counter() - started) * 1000
                hybrid.save(
                    task,
                    ids,
                    scores,
                    {
                        "bm25": first["timings_ms"]["total"],
                        "dense": second["timings_ms"]["total"],
                        "fusion": fusion_ms,
                        "total": first["timings_ms"]["total"]
                        + second["timings_ms"]["total"]
                        + fusion_ms,
                    },
                )
            if index % 100 == 0:
                print(
                    "dense", family, domain, index, "/", len(domain_tasks), flush=True
                )
        del vectors, rows
        torch.cuda.empty_cache()
    atomic_json(run_directory / f"{family}-query-encoding.json", model.truncation)


def ordered_passage_ids(ids, passages):
    return sorted(ids, key=lambda pid: (len(passages[pid]), pid))


def rerank(
    profile,
    tasks,
    identity,
    family,
    retrievers=("bge",),
    runtime_name=None,
    run_directory=None,
):
    run_directory = run_directory or ROOT / "runs"
    inputs = {
        retriever: {
            r["key"]: r for r in read_rows(run_directory / f"bm25_{retriever}.jsonl")
        }
        for retriever in retrievers
    }
    results = {
        retriever: Results(f"bm25_{retriever}_rerank_{family}", identity, run_directory)
        for retriever in inputs
    }
    shared = {
        row["scoring_key"]: row
        for output in results.values()
        for row in output.rows.values()
        if "scoring_key" in row
    }
    model = LocalModel(family, "reranker", profile)
    model.rerank("warm up", ["warm up passage"])
    model.truncation = {"items": 0, "truncated": 0, "query_truncated": 0}
    batch = profile["runtime"]["batch_size"]
    torch.cuda.reset_peak_memory_stats()
    for domain in DOMAINS:
        rows = {r["_id"]: r["text"] for r in corpus(domain)}
        domain_tasks = [q for q in tasks if q["domain"] == domain]
        for index, task in enumerate(domain_tasks, 1):
            for retriever, output in results.items():
                if task["key"] in output.rows:
                    continue
                candidates = inputs[retriever][task["key"]]
                ids = candidates["ids"][: profile["retrieval"]["rerank_k"]]
                ids = ordered_passage_ids(ids, rows)
                scoring_key = fingerprint(
                    {
                        "campaign": identity,
                        "family": family,
                        "domain": domain,
                        "query": task["query"],
                        "ids": ids,
                    }
                )
                if scoring_key in shared:
                    previous = shared[scoring_key]
                    elapsed = previous["timings_ms"]["rerank"]
                    output.save(
                        task,
                        previous["ids"],
                        previous["scores"],
                        {
                            "rerank": elapsed,
                            "total": candidates["timings_ms"]["total"] + elapsed,
                        },
                        scoring_key=scoring_key,
                        reused_identical_inference=True,
                        candidate_recall_at_50=candidates["metrics"]["recall@50"],
                    )
                    continue
                torch.cuda.synchronize()
                started = time.perf_counter()
                scores = []
                for offset in range(0, len(ids), batch):
                    scores.extend(
                        model.rerank(
                            task["query"],
                            [rows[pid] for pid in ids[offset : offset + batch]],
                        ).tolist()
                    )
                if not np.isfinite(scores).all():
                    raise ValueError(f"Non-finite reranker scores for {task['key']}")
                elapsed = (time.perf_counter() - started) * 1000
                order = sorted(range(len(ids)), key=lambda i: (-scores[i], ids[i]))
                output.save(
                    task,
                    [ids[i] for i in order],
                    [scores[i] for i in order],
                    {
                        "rerank": elapsed,
                        "total": candidates["timings_ms"]["total"] + elapsed,
                    },
                    scoring_key=scoring_key,
                    reused_identical_inference=False,
                    candidate_recall_at_50=candidates["metrics"]["recall@50"],
                )
                shared[scoring_key] = output.rows[task["key"]]
            if index == 1 or index % 25 == 0:
                print(
                    "rerank", family, domain, index, "/", len(domain_tasks), flush=True
                )
        del rows
    atomic_json(
        run_directory / (runtime_name or f"{family}-rerank-runtime.json"),
        {
            "truncation": model.truncation,
            "peak_gpu_bytes": torch.cuda.max_memory_allocated(),
            "batch_order": "ascending-passage-character-length",
            "unique_scoring_inputs": len(shared),
            "reused_identical_inference": sum(
                bool(row.get("reused_identical_inference"))
                for output in results.values()
                for row in output.rows.values()
            ),
        },
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["lexical", "dense", "rerank"])
    parser.add_argument("--family", choices=["bge"])
    args = parser.parse_args()
    profile = load_profile()
    tasks = queries(profile)
    identity = campaign_identity(profile)
    if args.stage == "lexical":
        lexical(profile, tasks, identity)
    elif args.family:
        {"dense": dense, "rerank": rerank}[args.stage](
            profile, tasks, identity, args.family
        )
    else:
        parser.error("--family is required for GPU stages")


if __name__ == "__main__":
    main()
