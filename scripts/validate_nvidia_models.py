import argparse
import csv
import json
import os
import time
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv


DEFAULT_MODELS = [
    "meta/llama-3.1-8b-instruct",
    "meta/llama-3.2-1b-instruct",
    "google/gemma-3-4b-it",
    "google/gemma-2-2b-it",
    "qwen/qwen2.5-coder-32b-instruct",
]


def _default_app_data_dir() -> Path:
    configured = os.getenv("APP_DATA_DIR")
    if configured:
        return Path(configured).resolve()
    return (Path(__file__).resolve().parents[1] / "data").resolve()


def _default_eval_dir() -> Path:
    configured = os.getenv("EVAL_DIR")
    if configured:
        return Path(configured).resolve()
    return (_default_app_data_dir() / "evaluation").resolve()


def _load_models_from_catalog(api_key: str, api_base: str, timeout_seconds: float) -> list[str]:
    headers = {"Authorization": f"Bearer {api_key}"}
    with httpx.Client(timeout=httpx.Timeout(timeout_seconds, connect=10.0)) as client:
        response = client.get(f"{api_base}/models", headers=headers)
        response.raise_for_status()
        data = response.json()["data"]
    return sorted(item["id"] for item in data)


def validate_models(
    models: list[str],
    timeout_seconds: float,
    rate_per_minute: int,
) -> list[dict]:
    load_dotenv(".env")
    api_key = os.getenv("NVIDIA_API_KEY", "")
    api_base = os.getenv("NVIDIA_API_BASE", "https://integrate.api.nvidia.com/v1").rstrip("/")
    if not api_key:
        raise RuntimeError("NVIDIA_API_KEY is missing from .env")

    if rate_per_minute <= 0:
        raise RuntimeError("rate_per_minute must be positive")

    interval_seconds = 60.0 / rate_per_minute
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    results: list[dict] = []
    next_allowed_at = time.monotonic()

    with httpx.Client(timeout=httpx.Timeout(timeout_seconds, connect=10.0)) as client:
        for index, model in enumerate(models, start=1):
            now = time.monotonic()
            sleep_for = next_allowed_at - now
            if sleep_for > 0:
                time.sleep(sleep_for)

            started_at = time.time()
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
                "max_tokens": 8,
                "temperature": 0.1,
            }
            try:
                response = client.post(f"{api_base}/chat/completions", headers=headers, json=payload)
                elapsed = round(time.time() - started_at, 2)
                preview = response.text[:240].replace("\n", " ")
                bucket = "callable" if response.status_code == 200 else "not_callable"
                results.append(
                    {
                        "index": index,
                        "model": model,
                        "bucket": bucket,
                        "status_code": response.status_code,
                        "elapsed_seconds": elapsed,
                        "preview": preview,
                    }
                )
            except httpx.ReadTimeout as exc:
                elapsed = round(time.time() - started_at, 2)
                results.append(
                    {
                        "index": index,
                        "model": model,
                        "bucket": "timeout",
                        "status_code": None,
                        "elapsed_seconds": elapsed,
                        "preview": f"ReadTimeout: {exc}",
                    }
                )
            except Exception as exc:  # noqa: BLE001
                elapsed = round(time.time() - started_at, 2)
                results.append(
                    {
                        "index": index,
                        "model": model,
                        "bucket": "other_error",
                        "status_code": None,
                        "elapsed_seconds": elapsed,
                        "preview": f"{type(exc).__name__}: {exc}",
                    }
                )

            next_allowed_at = max(next_allowed_at + interval_seconds, time.monotonic())

    return results


def save_results(results: list[dict], output_prefix: str) -> tuple[Path, Path]:
    eval_dir = _default_eval_dir()
    eval_dir.mkdir(parents=True, exist_ok=True)
    json_path = eval_dir / f"{output_prefix}.json"
    csv_path = eval_dir / f"{output_prefix}.csv"

    summary = {
        "generated_at": datetime.now().isoformat(),
        "total_models": len(results),
        "callable_count": sum(1 for r in results if r["bucket"] == "callable"),
        "not_callable_count": sum(1 for r in results if r["bucket"] == "not_callable"),
        "timeout_count": sum(1 for r in results if r["bucket"] == "timeout"),
        "other_error_count": sum(1 for r in results if r["bucket"] == "other_error"),
        "results": results,
    }

    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["index", "model", "bucket", "status_code", "elapsed_seconds", "preview"],
        )
        writer.writeheader()
        writer.writerows(results)
    return json_path, csv_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--rate-per-minute", type=int, default=30)
    parser.add_argument("--all", action="store_true", help="Probe all models returned by /models")
    parser.add_argument("--models", nargs="*", default=None)
    parser.add_argument("--output-prefix", default=f"nvidia_model_matrix_{datetime.now().strftime('%Y-%m-%d')}")
    args = parser.parse_args()

    load_dotenv(".env")
    api_key = os.getenv("NVIDIA_API_KEY", "")
    api_base = os.getenv("NVIDIA_API_BASE", "https://integrate.api.nvidia.com/v1").rstrip("/")
    if not api_key:
        raise RuntimeError("NVIDIA_API_KEY is missing from .env")

    if args.all:
        models = _load_models_from_catalog(api_key, api_base, args.timeout)
    elif args.models:
        models = args.models
    else:
        models = DEFAULT_MODELS

    results = validate_models(models, args.timeout, args.rate_per_minute)
    json_path, csv_path = save_results(results, args.output_prefix)

    for item in results:
        print(
            f"{item['index']:03d}. {item['model']} | bucket={item['bucket']} | "
            f"status={item['status_code']} | elapsed={item['elapsed_seconds']}s"
        )

    print(
        json.dumps(
            {
                "json_path": str(json_path),
                "csv_path": str(csv_path),
                "total_models": len(results),
                "callable_count": sum(1 for r in results if r["bucket"] == "callable"),
                "not_callable_count": sum(1 for r in results if r["bucket"] == "not_callable"),
                "timeout_count": sum(1 for r in results if r["bucket"] == "timeout"),
                "other_error_count": sum(1 for r in results if r["bucket"] == "other_error"),
                "rate_per_minute": args.rate_per_minute,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
