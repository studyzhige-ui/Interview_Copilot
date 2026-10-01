"""Official M3 sparse head, isolated full-corpus lexical replacement experiment."""

import argparse
import ast
import gc
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from filelock import FileLock
from scipy import sparse

from .download import ROOT
from .freeze_runtime import hash_file
from .local_models import LocalModel, np, torch
from .m3_campaign import profile, MANIFEST
from .optimize_m3 import tasks_for
from .prepare import DOMAINS
from .report import summarize
from .rewrite import atomic_json
from .run import Results, corpus, fusion, read_rows, rerank, topk

OUT = ROOT / "sparse-m3-v1"
RUNS = OUT / "runs"
HEAD = OUT / "head/sparse_linear.pt"
MODEL_SHA = "b5e0ce3470abf5ef3831aa1bd5553b486803e83251590ab7ff35a117cf6aad38"
HEAD_SHA = "45c93804d2142b8f6d7ec6914ae23a1eee9c6a1d27d83d908a20d2afb3595ad9"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


class SparseM3(LocalModel):
    def __init__(self):
        super().__init__("bge_m3", "embedding", profile())
        if hash_file(HEAD) != HEAD_SHA:
            raise ValueError("Sparse head hash mismatch")
        self.head = torch.nn.Linear(1024, 1)
        self.head.load_state_dict(
            torch.load(HEAD, map_location="cpu", weights_only=True)
        )
        self.head.to(device="cuda", dtype=self.model.dtype).eval()
        self.unused = {
            self.tokenizer.cls_token_id,
            self.tokenizer.eos_token_id,
            self.tokenizer.pad_token_id,
            self.tokenizer.unk_token_id,
        }

    @torch.inference_mode()
    def encode_sparse(self, texts, verify=False):
        inputs = self.tokenizer(
            texts, padding=True, truncation=True, max_length=512, return_tensors="pt"
        ).to("cuda")
        hidden = self.model(**inputs).last_hidden_state
        weights = torch.relu(self.head(hidden)).squeeze(-1).float().cpu().numpy()
        tokens = inputs["input_ids"].cpu().numpy()
        output = []
        for text, ids, values in zip(texts, tokens, weights):
            row = {}
            if text.strip():
                for token, value in zip(ids, values):
                    if token not in self.unused and value > 0:
                        row[int(token)] = max(row.get(int(token), 0.0), float(value))
            output.append(row)
        if verify:
            # Execute only the reviewed official sparse formula, not its package.
            tree = ast.parse((OUT / "official-0.py").read_text(encoding="utf-8"))
            function = next(
                n
                for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "_sparse_embedding"
            )
            ns = {"torch": torch}
            exec(
                compile(
                    ast.Module(body=[function], type_ignores=[]),
                    "official_sparse_formula",
                    "exec",
                ),
                ns,
            )
            from types import SimpleNamespace

            obj = SimpleNamespace(
                sparse_linear=self.head,
                training=False,
                vocab_size=self.tokenizer.vocab_size,
                tokenizer=self.tokenizer,
            )
            reference = (
                ns["_sparse_embedding"](obj, hidden, inputs["input_ids"])
                .float()
                .cpu()
                .numpy()
            )
            actual = matrix(output, self.tokenizer.vocab_size).toarray()
            if not np.array_equal(reference, actual):
                raise ValueError("Sparse weights differ from official formula")
        return output


def matrix(rows, vocab=250002):
    data, indices, indptr = [], [], [0]
    for row in rows:
        for token, weight in sorted(row.items()):
            indices.append(token)
            data.append(weight)
        indptr.append(len(data))
    return sparse.csr_matrix(
        (
            np.asarray(data, dtype=np.float32),
            np.asarray(indices, dtype=np.int32),
            np.asarray(indptr, dtype=np.int64),
        ),
        shape=(len(rows), vocab),
    )


def identity():
    return read(OUT / "manifest.json")["identity"]


def prepare():
    paths = [
        Path(__file__),
        ROOT / "queries.jsonl",
        ROOT / "rewritten.jsonl",
        ROOT / "tasks.jsonl",
        ROOT / "optimization-m3-v1/split.json",
        MANIFEST,
        HEAD,
        ROOT / "runs/bge_m3_dense.jsonl",
        ROOT / "runs/bm25_bge_m3_rerank_bge_m3.jsonl",
        Path(__file__).with_name("local_models.py"),
        Path(__file__).with_name("run.py"),
    ]
    manifest = {
        "files": {str(p): hash_file(p) for p in paths},
        "prompt": "v1 unchanged",
        "model_revision": "5617a9f61b028005a4858fdac845db406aefb181",
        "corpus": read(ROOT / "data_audit.json")["corpora"],
        "hypothesis": "replace BM25 with M3 learned sparse token weights; dense unchanged",
        "retrieval": "sparse50+dense50 -> equal RRF60 -> 50 candidates -> M3 rerank512 -> top10",
        "new_llm_calls": 0,
        "grid_search": False,
        "blind_test": False,
        "material_gain_gate": "both datasets nondecreasing nDCG/Recall10 and mean dataset-macro nDCG gain >=0.02 on internal validation",
    }
    from .profile import fingerprint

    manifest["identity"] = fingerprint(manifest)
    if (OUT / "manifest.json").exists() and read(OUT / "manifest.json") != manifest:
        raise ValueError("Frozen sparse experiment changed")
    model_dir = Path(profile()["models"]["bge_m3_embedding"]["path"])
    if hash_file(model_dir / "pytorch_model.bin") != MODEL_SHA:
        raise ValueError("Local backbone does not match official sparse head revision")
    if (
        hash_file(model_dir / "tokenizer.json")
        != "21106b6d7dab2952c1d496fb21d5dc9db75c28ed361a05f5020bbba27810dd08"
    ):
        raise ValueError("Tokenizer mismatch")
    atomic_json(OUT / "manifest.json", manifest)
    model = SparseM3()
    texts = [
        "What is BGE M3?",
        "BGE M3 supports dense and sparse retrieval.",
        "Bananas are fruit.",
    ]
    vectors = matrix(model.encode_sparse(texts, verify=True))
    scores = (vectors[0] @ vectors[1:].T).toarray()[0]
    assert scores[0] > scores[1] and np.isfinite(vectors.data).all()
    atomic_json(
        OUT / "smoke.json",
        {
            "official_formula_exact_match": True,
            "scores": scores.tolist(),
            "backbone_and_tokenizer_hash_match": True,
        },
    )
    print("Sparse smoke passed; official head/backbone/tokenizer verified", flush=True)


def encode():
    model = SparseM3()
    for domain in DOMAINS:
        rows = corpus(domain)
        folder = OUT / "index" / domain
        folder.mkdir(parents=True, exist_ok=True)
        shards = []
        for start in range(0, len(rows), 1024):
            path = folder / f"{start:07d}.npz"
            shards.append(path)
            if path.exists():
                continue
            subset = rows[start : start + 1024]
            order = sorted(range(len(subset)), key=lambda i: len(subset[i]["text"]))
            vectors = [None] * len(subset)
            for offset in range(0, len(order), 8):
                indices = order[offset : offset + 8]
                encoded = model.encode_sparse([subset[i]["text"] for i in indices])
                for i, vector in zip(indices, encoded):
                    vectors[i] = vector
            value = matrix(vectors)
            temporary = path.with_suffix(".tmp.npz")
            sparse.save_npz(temporary, value)
            temporary.replace(path)
            atomic_json(
                OUT / "index-progress.json",
                {
                    "domain": domain,
                    "completed": min(start + 1024, len(rows)),
                    "total": len(rows),
                    "identity": identity(),
                    "updated_at": time.time(),
                },
            )
            print(
                "sparse index",
                domain,
                min(start + 1024, len(rows)),
                "/",
                len(rows),
                flush=True,
            )
        atomic_json(
            folder / "complete.json",
            {"rows": len(rows), "shards": len(shards), "identity": identity()},
        )
        del rows
        gc.collect()


def retrieve():
    tasks = tasks_for()
    dense = {r["key"]: r for r in read_rows(ROOT / "runs/bge_m3_dense.jsonl")}
    lexical = Results("m3_sparse", identity(), RUNS)
    hybrid = Results(
        "bm25_bge_m3", identity(), RUNS
    )  # standard runner input name; metadata identifies sparse replacement
    model = SparseM3()
    model.encode_sparse(["warm up"])
    for domain in DOMAINS:
        folder = OUT / "index" / domain
        meta = read(folder / "complete.json")
        assert meta["identity"] == identity()
        docs = corpus(domain)
        index = sparse.vstack(
            [sparse.load_npz(p) for p in sorted(folder.glob("[0-9]*.npz"))],
            format="csr",
        )
        assert index.shape == (len(docs), 250002)
        for t in [t for t in tasks if t["domain"] == domain]:
            if t["key"] in hybrid.rows:
                continue
            torch.cuda.synchronize()
            started = time.perf_counter()
            query = matrix(model.encode_sparse([t["query"]]))
            scores = (index @ query.T).toarray().ravel()
            selected = topk(scores, 50, positive=True)
            elapsed = 1000 * (time.perf_counter() - started)
            ids = [docs[i]["_id"] for i in selected]
            lexical.save(t, ids, scores[selected].tolist(), {"total": elapsed})
            started = time.perf_counter()
            fused, values = fusion(ids, dense[t["key"]]["ids"], 50, 60)
            fused_ms = 1000 * (time.perf_counter() - started)
            hybrid.save(
                t,
                fused,
                values,
                {
                    "sparse": elapsed,
                    "cached_dense": dense[t["key"]]["timings_ms"]["total"],
                    "fusion": fused_ms,
                    "total": elapsed
                    + fused_ms
                    + dense[t["key"]]["timings_ms"]["total"],
                },
                actual_retriever="m3_sparse_plus_dense",
            )
        print("retrieved", domain, flush=True)
        del index, docs
        gc.collect()


def report():
    tasks = tasks_for()
    current = {r["key"]: r for r in read_rows(RUNS / "bm25_bge_m3_rerank_bge_m3.jsonl")}
    baseline = {
        r["key"]: r for r in read_rows(ROOT / "runs/bm25_bge_m3_rerank_bge_m3.jsonl")
    }
    assert len(current) == len(tasks) and current.keys() == {t["key"] for t in tasks}
    summaries = {}
    for split in ("all", "tune", "validation"):
        summaries[split] = {
            d: {
                "old": summarize(
                    [
                        baseline[t["key"]]
                        for t in tasks
                        if t["dataset"] == d and (split == "all" or t["split"] == split)
                    ]
                ),
                "new": summarize(
                    [
                        current[t["key"]]
                        for t in tasks
                        if t["dataset"] == d and (split == "all" or t["split"] == split)
                    ]
                ),
            }
            for d in ("mtrag-human", "mtragun-human")
        }
    deltas = {
        d: {
            m: s["new"]["domain_macro"][m] - s["old"]["domain_macro"][m]
            for m in ("ndcg@10", "recall@10", "recall@50")
        }
        for d, s in summaries["validation"].items()
    }
    passed = (
        all(v[m] >= 0 for v in deltas.values() for m in ("ndcg@10", "recall@10"))
        and sum(v["ndcg@10"] for v in deltas.values()) / 2 >= 0.02
    )
    atomic_json(
        OUT / "results.json",
        {
            "summary": summaries,
            "validation_deltas": deltas,
            "material_gain_gate_passed": passed,
            "new_llm_calls": 0,
            "latency_note": "sparse and reranker freshly measured; dense timing from old cache; separate forward passes",
        },
    )
    lines = [
        "# BGE-M3 稀疏召回替换实验",
        "",
        "固定原v1改写、M3模型和50候选预算；只将BM25替换为官方M3稀疏检索。",
        "",
        "| 划分 | 数据集 | 旧/新 nDCG@10 | 旧/新 Recall@10 | 旧/新候选 Recall@50 |",
        "|---|---|---|---|---|",
    ]
    for split, ds in summaries.items():
        for d, s in ds.items():
            a, b = s["old"]["domain_macro"], s["new"]["domain_macro"]
            lines.append(
                f"| {split} | {d} | {a['ndcg@10']:.4f}/{b['ndcg@10']:.4f} | {a['recall@10']:.4f}/{b['recall@10']:.4f} | {a['recall@50']:.4f}/{b['recall@50']:.4f} |"
            )
    lines += [
        "",
        f"通过预设实质收益门槛（内部验证平均nDCG至少+0.02且两数据集nDCG/Recall均不退步）：{passed}。",
        "已有数据非独立盲测；不自动更改生产配置。索引构建耗时不计入在线查询耗时。",
        "稀疏与重排时间为新测，稠密时间复用旧缓存；当前稀疏单独前向计算，不宣称免费或零延迟。",
        "",
    ]
    (OUT / "README.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "stage", choices=("prepare", "encode", "retrieve", "rerank", "report", "all")
    )
    args = parser.parse_args()
    RUNS.mkdir(parents=True, exist_ok=True)
    if args.stage == "all":
        with FileLock(str(OUT / "campaign.lock"), timeout=1):
            state = {
                "state": "running",
                "pid": os.getpid(),
                "started_at": time.time(),
                "new_llm_calls": 0,
            }
            try:
                for stage in ("encode", "retrieve", "rerank", "report"):
                    state.update(stage=stage, updated_at=time.time())
                    atomic_json(OUT / "status.json", state)
                    subprocess.run(
                        [
                            sys.executable,
                            "-X",
                            "utf8",
                            "-u",
                            "-m",
                            "evaluation.mtrag.sparse_m3",
                            stage,
                        ],
                        check=True,
                    )
                state.update(state="complete", stage="complete")
            except Exception as exc:
                state.update(state="failed", error_type=type(exc).__name__)
                raise
            finally:
                state["updated_at"] = time.time()
                atomic_json(OUT / "status.json", state)
        return
    if args.stage != "prepare":
        if any(
            hash_file(Path(p)) != h
            for p, h in read(OUT / "manifest.json")["files"].items()
        ):
            raise ValueError("Frozen input changed")
    if args.stage == "rerank":
        rerank(
            profile(),
            tasks_for(),
            identity(),
            "bge_m3",
            retrievers=("bge_m3",),
            run_directory=RUNS,
        )
    else:
        {"prepare": prepare, "encode": encode, "retrieve": retrieve, "report": report}[
            args.stage
        ]()


if __name__ == "__main__":
    main()
