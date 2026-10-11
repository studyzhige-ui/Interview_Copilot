"""Read-only deployed API checks with an existing bearer token."""

import argparse
import json
import os

import httpx


def run(base_url: str, token: str) -> dict:
    checks = []
    with httpx.Client(
        base_url=base_url.rstrip("/"),
        timeout=15,
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        for path in (
            "/api/v1/health/live",
            "/api/v1/health/ready",
            "/api/v1/auth/me",
            "/api/v1/resumes",
            "/api/v1/chat/sessions",
        ):
            response = client.get(path)
            response.raise_for_status()
            response.json()
            checks.append(path)
    return {
        "status": "passed",
        "scope": "read-only HTTP and account access",
        "checks": checks,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    args = parser.parse_args()
    print(json.dumps(run(args.base_url, os.environ["IC_SMOKE_TOKEN"]), indent=2))
