"""Real Chromium against the built SPA; this is not backend workflow acceptance."""

import functools
import http.server
import os
from pathlib import Path
import threading

import pytest


def test_production_auth_shell_and_form_validation():
    if os.environ.get("IC_RUN_BROWSER") != "1":
        pytest.skip("IC_RUN_BROWSER=1 and built frontend required")
    from playwright.sync_api import sync_playwright, expect
    from fastapi.testclient import TestClient
    from app.main import app

    root = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    assert (root / "index.html").is_file(), "Build frontend before browser acceptance"
    api = TestClient(app)

    class ApplicationHandler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/api/v1/"):
                response = api.get(self.path)
                self.send_response(response.status_code)
                self.send_header(
                    "Content-Type",
                    response.headers.get("content-type", "application/json"),
                )
                self.end_headers()
                self.wfile.write(response.content)
            else:
                super().do_GET()

    handler = functools.partial(ApplicationHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{server.server_port}/")
            expect(page.get_by_text("Interview Copilot", exact=True)).to_be_visible()
            submit = page.locator("form button[type=submit]")
            expect(submit).to_be_disabled()
            page.get_by_placeholder("请输入用户名").fill("contract-user")
            page.get_by_placeholder("至少 6 位").fill("valid-password")
            expect(submit).to_be_enabled()
            page.get_by_role("button", name="忘记密码？").click()
            expect(page.get_by_text("重置密码", exact=True).first).to_be_visible()
            assert not errors
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
