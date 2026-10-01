"""Audited, resumable v2 rewrite preparation; no retrieval or answer generation."""

import argparse
import hashlib
import json
import os
import statistics
import time

import httpx
from dotenv import dotenv_values
from filelock import FileLock

from .profile import fingerprint, load_profile
from .rewrite import ROOT, atomic_json, cache_identity, rewrite_query

DATA = ROOT / "data/evaluation/mtrag"
OUT = DATA / "rewrite-v2.1"
PRIORITY = [
    "mtrag-human::dd82f0f978316e73618cf0addd369cd8<::>9",
    "mtrag-human::81afaf82a0d9a5fad6eaa196f8d9641c<::>4",
    "mtragun-human::3a44984a1b74e5be70f01e8a60c3ea14<::>2",
    "mtrag-human::5815bb4a99e2a0d8a986348da4c49083<::>7",
]


def rows(path):
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def prepare():
    records = rows(DATA / "queries.jsonl")
    profile = load_profile()
    profile["rewrite"]["prompt_version"] = "v2.1"
    upstream = {
        name: {
            r["task_id"]: r
            for r in rows(DATA / "upstream" / name / "generation_tasks/reference.jsonl")
        }
        for name in ("mtrag-human", "mtragun-human")
    }
    digests, legacy, turn_counts, char_counts = {}, set(), [], []
    identifiers = set()
    for record in records:
        if record["query_id"] in identifiers:
            raise ValueError("Duplicate query ID")
        identifiers.add(record["query_id"])
        name, task_id = record["query_id"].split("::", 1)
        source = upstream[name][task_id]
        expected = [
            {
                "role": {"user": "user", "agent": "assistant"}[m["speaker"]],
                "content": m["text"],
            }
            for m in source["input"]
        ]
        body, digest = cache_identity(record, profile)
        if (
            record["messages"] != expected
            or json.loads(body["messages"][1]["content"]) != expected
        ):
            raise ValueError(f"History mismatch: {record['query_id']}")
        if len(expected) != 2 * int(source["turn"]) - 1:
            raise ValueError(f"Incomplete turn history: {record['query_id']}")
        old_key = cache_identity(record, load_profile())[1]
        cached = json.loads(
            (DATA / "rewrites" / f"{old_key}.json").read_text(encoding="utf-8")
        )
        if cached["request_sha256"] != old_key:
            raise ValueError("Legacy cache mismatch")
        legacy.add(old_key)
        digests[record["query_id"]] = digest
        turn_counts.append(len(expected))
        char_counts.append(sum(len(m["content"]) for m in expected))
    audit = {
        "queries": len(records),
        "unique_requests": len(set(digests.values())),
        "full_source_history_matches": len(records),
        "legacy_cache_matches": len(legacy),
        "single_turn_queries": turn_counts.count(1),
        "max_messages": max(turn_counts),
        "max_history_characters": max(char_counts),
        "input_truncation": False,
        "current_answer_future_turns_qrels_sent": False,
    }
    manifest = {
        "profile": profile["rewrite"],
        "audit": audit,
        "queries_sha256": hashlib.sha256(
            (DATA / "queries.jsonl").read_bytes()
        ).hexdigest(),
        "prompt": cache_identity(records[0], profile)[0]["messages"][0]["content"],
        "request_identities_sha256": fingerprint(digests),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "manifest.json"
    if path.exists() and json.loads(path.read_text(encoding="utf-8")) != manifest:
        raise ValueError("Campaign input changed; use a separate campaign version")
    atomic_json(path, manifest)
    return records, profile, digests, audit


def run(limit, audit_only):
    records, profile, digests, audit = prepare()
    if audit_only:
        print(json.dumps(audit), flush=True)
        return
    key_name = profile["rewrite"]["api_key_env"]
    api_key = (
        os.environ.get(key_name) or dotenv_values(ROOT / ".env").get(key_name) or ""
    )
    # Only this explicit preparation job may populate the paid rewrite cache.
    unique = {}
    order = sorted(
        records,
        key=lambda r: (
            PRIORITY.index(r["query_id"])
            if r["query_id"] in PRIORITY
            else len(PRIORITY)
        ),
    )
    for record in order:
        unique.setdefault(digests[record["query_id"]], record)
    selected = list(unique.items())[:limit] if limit else list(unique.items())
    started = time.time()
    success, failures, new_calls = {}, [], 0

    def status(state):
        atomic_json(
            OUT / "status.json",
            {
                "state": state,
                "pid": os.getpid(),
                "started_at": started,
                "updated_at": time.time(),
                "total_unique": len(unique),
                "selected_unique": len(selected),
                "processed": len(success) + len(failures),
                "successful": len(success),
                "failed": len(failures),
                "new_calls_this_run": new_calls,
                "output": str(OUT / "rewritten.jsonl"),
                "errors": failures,
            },
        )

    status("running")
    with httpx.Client(transport=httpx.HTTPTransport(retries=0)) as client:
        for digest, record in selected:
            try:
                result = rewrite_query(
                    record, profile, client, api_key, DATA / "rewrites", allow_api=True
                )
                success[digest] = result
                new_calls += int(not result["cache_hit"])
            except Exception as exc:
                failures.append(
                    {
                        "query_id": record["query_id"],
                        "request_sha256": digest,
                        "error_type": type(exc).__name__,
                    }
                )
                # Stop on the first failure: do not spend the rest of the budget
                # when credentials, provider availability, or output validity fail.
                status("failed")
                print(
                    f"Stopped: {type(exc).__name__}; inspect saved receipt for {digest}",
                    flush=True,
                )
                return
            status("running")
            if (
                len(success) == 1
                or len(success) % 25 == 0
                or len(success) == len(selected)
            ):
                print(
                    f"rewrites {len(success)}/{len(selected)} new_calls={new_calls}",
                    flush=True,
                )
    selected_records = [r for r in records if digests[r["query_id"]] in success]
    old = {r["query_id"]: r["query"] for r in rows(DATA / "rewritten.jsonl")}
    output = [
        {**success[digests[r["query_id"]]], "query_id": r["query_id"]}
        for r in selected_records
    ]
    name = "rewritten.jsonl" if len(success) == len(unique) else "smoke.jsonl"
    temporary = OUT / (name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in output:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(OUT / name)
    changes = [
        {
            "query_id": r["query_id"],
            "messages": r["messages"],
            "old_query": old[r["query_id"]],
            "new_query": success[digests[r["query_id"]]]["query"],
        }
        for r in selected_records
    ]
    atomic_json(OUT / "comparison.json", {"rows": changes})
    usage = {}
    for result in success.values():
        for key, value in (result.get("usage") or {}).items():
            if isinstance(value, (int, float)):
                usage[key] = usage.get(key, 0) + value
    summary = {
        "audit": audit,
        "output_rows": len(output),
        "unique_successful": len(success),
        "new_calls_this_run": new_calls,
        "changed_from_v1": sum(r["old_query"] != r["new_query"] for r in changes),
        "identical_to_current_question": sum(
            r["new_query"] == r["messages"][-1]["content"] for r in changes
        ),
        "unique_response_usage": usage,
        "retrieval_improvement_verified": False,
    }
    atomic_json(OUT / "summary.json", summary)
    if len(success) == len(unique):
        latencies = sorted(r["latency_ms"] for r in success.values())
        report = [
            "# 查询改写 v2.1 完成报告",
            "",
            f"已完成 {len(output)} 条题目、{len(success)} 个唯一输入的改写。重复输入复用缓存。",
            "",
            "## 输入与缓存",
            "",
            f"- {audit['full_source_history_matches']} 条输入与官方提供的完整历史逐条一致，且消息数与轮次一致。",
            f"- 最长 {audit['max_messages']} 条消息、{audit['max_history_characters']} 个正文字符；未截断或摘要替换。",
            "- 不发送当前参考答案、未来轮次、qrels 或检索证据。",
            "- 新提示词按完整请求内容生成新缓存键，旧版结果保留；断点续跑复用已保存响应。",
            "",
            "## 改写统计",
            "",
            f"- 相对旧版文字有变化：{summary['changed_from_v1']} 条。",
            f"- 与当前用户问题完全相同：{summary['identical_to_current_question']} 条。",
            f"- 唯一请求 token 用量：{json.dumps(usage, ensure_ascii=False)}。",
            f"- 首次 API 调用延迟中位数：{statistics.median(latencies):.1f} ms；P95：{latencies[int((len(latencies) - 1) * 0.95)]:.1f} ms。",
            "- 上述延迟来自缓存中的首次 API 调用，不是本轮缓存读取时间。",
            "",
            "## 结果文件与边界",
            "",
            "- `rewritten.jsonl`：完整新版改写，供后续检索对照使用。",
            "- `comparison.json`：每题完整历史、旧改写和新改写。",
            "- `manifest.json`：提示词、参数、输入指纹及历史完整性审计。",
            "- `summary.json` / `status.json`：统计和最终执行状态。",
            "- 完成改写和结构校验不等于语义逐条验收，更不等于检索指标提升。此次没有运行检索或答案生成。",
            "- 四个诊断案例的人工检查见 `smoke-review.json`；全量后续仍需固定检索配置进行对照。",
            "",
        ]
        (OUT / "README.md").write_text("\n".join(report), encoding="utf-8")
    status("complete" if len(success) == len(unique) else "smoke_complete")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--audit-only", action="store_true")
    args = parser.parse_args()
    if args.limit is not None and args.limit <= 0:
        parser.error("limit must be positive")
    OUT.mkdir(parents=True, exist_ok=True)
    with FileLock(str(OUT / "campaign.lock"), timeout=1):
        try:
            run(args.limit, args.audit_only)
        except Exception as exc:
            atomic_json(
                OUT / "status.json",
                {
                    "state": "failed",
                    "pid": os.getpid(),
                    "updated_at": time.time(),
                    "error_type": type(exc).__name__,
                },
            )
            raise


if __name__ == "__main__":
    main()
