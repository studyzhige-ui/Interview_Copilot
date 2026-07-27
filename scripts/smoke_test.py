"""Exercise the deployed API's core authenticated Web flow."""

from __future__ import annotations

import argparse
import json

import httpx


def run(base_url: str, username: str, password: str) -> dict:
    checks: list[str] = []
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=15) as client:
        for path in ("/api/v1/health/live", "/api/v1/health/ready"):
            response = client.get(path)
            response.raise_for_status()
            checks.append(path)

        response = client.post(
            "/api/v1/auth/login",
            data={"username": username, "password": password},
        )
        response.raise_for_status()
        token = response.json()["access_token"]
        client.headers["Authorization"] = f"Bearer {token}"

        for path in ("/api/v1/auth/me", "/api/v1/capabilities/edition"):
            response = client.get(path)
            response.raise_for_status()
            checks.append(path)

        response = client.post(
            "/api/v1/chat/sessions",
            json={"type": "general", "title": "Release smoke test"},
        )
        response.raise_for_status()
        session_id = response.json()["session_id"]
        try:
            response = client.get("/api/v1/chat/sessions")
            response.raise_for_status()
            if session_id not in {item["session_id"] for item in response.json()}:
                raise RuntimeError("Created session was not returned by list")
            response = client.patch(
                f"/api/v1/chat/sessions/{session_id}/title",
                json={"title": "Release smoke test updated"},
            )
            response.raise_for_status()
            checks.extend(["create_session", "list_sessions", "rename_session"])
        finally:
            response = client.delete(f"/api/v1/chat/sessions/{session_id}")
            response.raise_for_status()
            checks.append("delete_session")
    return {"status": "passed", "checks": checks}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.base_url, args.username, args.password), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
