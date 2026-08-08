from app.api import operations
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(operations.router, prefix="/api/v1")
    return TestClient(app)


def test_liveness_is_process_only():
    response = _client().get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readiness_reports_dependency_failure(monkeypatch):
    async def unavailable():
        return {"database": "ok", "redis": "unavailable"}

    monkeypatch.setattr(operations, "dependency_status", unavailable)
    response = _client().get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json()["dependencies"]["redis"] == "unavailable"
