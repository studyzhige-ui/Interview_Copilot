"""Every declared bearer-protected HTTP route must reject anonymous requests."""

import re

from fastapi.testclient import TestClient
from app.main import app


def test_all_bearer_protected_routes_reject_missing_credentials():
    checked = []
    client = TestClient(app, raise_server_exceptions=False)
    operation_ids = set()
    for path, methods in app.openapi()["paths"].items():
        for method, operation in methods.items():
            if method not in {"get", "post", "put", "patch", "delete", "head"}:
                continue
            assert operation["operationId"] not in operation_ids
            operation_ids.add(operation["operationId"])
            if not operation.get("security"):
                continue
            url = re.sub(r"\{[^}]+\}", "1", path)
            response = client.request(method, url, json={})
            assert response.status_code == 401, (method, path, response.status_code)
            checked.append((method, path))
    assert len(checked) >= 200
