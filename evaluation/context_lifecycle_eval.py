"""Synthetic live continuation evaluation; never loads a user's conversation."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


async def evaluate() -> dict:
    from app.core.llm_client_factory import build_provider_client_for_role
    from app.core.model_provider_adapter import (
        ModelProviderAdapter,
        build_provider_request,
    )
    from app.conversation.context_window import compact, item

    client, profile = await build_provider_client_for_role("primary")
    history = [
        {"role": "system", "content": "依据对话确认任务，禁止猜测缺失事实。"},
        item(
            {
                "role": "user",
                "content": "帮我找上海的后端岗位，月薪底线30k，不接受其他城市。请先比较，未经确认不要投递。",
            },
            "user",
        ),
        {"role": "assistant", "content": "找到A、B两个候选，尚未投递。"},
        item(
            {"role": "user", "content": "暂停A，只核实B薪资，职位是后端工程师。"},
            "user",
        ),
        {
            "role": "assistant",
            "content": "B薪资仍待确认，下一步核实。文件为resume.pdf。",
        },
    ]
    first, first_report = await compact(history, client=client, profile=profile)
    first.append(
        item(
            {
                "role": "user",
                "content": "更正薪资底线为35k，其他约束不变。B薪资还没查到，未授权投递。",
            },
            "user",
        )
    )
    second, second_report = await compact(first, client=client, profile=profile)
    # Serialize/reload the replacement projection before continuation.
    restored = json.loads(json.dumps(second, ensure_ascii=False))
    restored.append(
        {
            "role": "user",
            "content": '继续，确认任务与限制。只输出JSON：{"city":"城市","minimum_salary_k":整数,"candidate":"A或B","salary_known":布尔,"may_submit":布尔,"file":"文件名"}。',
        }
    )
    request = build_provider_request(
        messages=restored, tools=None, max_tokens=2000, temperature=0.2
    )
    stream = await ModelProviderAdapter(client=client, profile=profile).start_stream(
        request
    )
    parts = []
    async for event in stream:
        parts.append(event.text_delta)
    raw = "".join(parts).strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
    answer = json.loads(raw)
    checks = {
        "latest_constraint": answer.get("minimum_salary_k") == 35,
        "location_preserved": answer.get("city") == "上海",
        "pending_target": answer.get("candidate") == "B",
        "unknown_not_promoted_to_fact": answer.get("salary_known") is False,
        "authorization_preserved": answer.get("may_submit") is False,
        "artifact_preserved": answer.get("file") == "resume.pdf",
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "model": profile.id,
        "compactions": [first_report, second_report],
        "answer": answer,
        "scope": "Selected primary model, two original-template compactions, serialized checkpoint continuation; synthetic data only.",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.live:
        parser.error("--live explicitly enables three synthetic model calls")
    result = asyncio.run(evaluate())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
