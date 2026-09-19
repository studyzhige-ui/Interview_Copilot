"""Real Chromium, production HTTP/auth/SQL and refresh-after-COMMIT response loss.

Requires IC_RUN_BROWSER=1 and a built frontend. Deliberately not advertised as
live inference, real Gmail/OAuth or learning-effect quality evidence.
"""

import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import httpx
import pytest

from app.core.security import get_password_hash
from app.models.user import User
from app.models.interview_record import InterviewRecord
from app.models.job_opportunity import NextAction
from tests.test_db.test_budget_and_invitation_recovery_postgres import (
    database as database_fixture,
)
from tests.test_db.test_alembic_migrations import fresh_pg_db  # noqa: F401

database = database_fixture

pytestmark = pytest.mark.skipif(
    os.environ.get("IC_RUN_BROWSER") != "1", reason="explicit real-browser campaign"
)


@pytest.fixture
def browser_app(database, tmp_path):
    url, _, factory = database
    from playwright.sync_api import sync_playwright

    root = Path(__file__).resolve().parents[3]
    assert (root / "frontend/dist/index.html").is_file(), (
        "Build the real frontend before the browser campaign"
    )
    with factory() as db:
        db.add(
            User(
                username="browser-owner",
                hashed_password=get_password_hash("synthetic-test-password"),
            )
        )
        db.commit()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    address = f"http://127.0.0.1:{port}"
    env = dict(
        os.environ,
        DATABASE_URL=url,
        REDIS_URL=os.environ.get("TEST_REDIS_URL", "redis://127.0.0.1:6379/0"),
        SECRET_KEY="isolated-browser-secret-not-production-32-bytes",
        IC_BROWSER_TEST="1",
        STORAGE_DIR=str(tmp_path / "storage"),
        PYTHONPATH=str(root / "backend"),
        LOG_LEVEL="WARNING",
    )
    log_path = tmp_path / "api.log"
    with log_path.open("w") as log:
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "tests.browser.api_host:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--no-access-log",
            ],
            env=env,
            cwd=root,
            stdout=log,
            stderr=log,
        )
        try:
            end = time.monotonic() + 30
            while time.monotonic() < end:
                assert proc.poll() is None, log_path.read_text()
                try:
                    if (
                        httpx.get(address + "/openapi.json", timeout=1).status_code
                        == 200
                    ):
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            else:
                pytest.fail("browser app startup timed out\n" + log_path.read_text())
            with sync_playwright() as playwright:
                executable = os.environ.get("IC_CHROMIUM_EXECUTABLE")
                browser = playwright.chromium.launch(
                    headless=True, executable_path=executable
                )
                context = browser.new_context(
                    locale="zh-CN", timezone_id="Asia/Shanghai"
                )
                try:
                    yield address, context, factory
                finally:
                    context.close()
                    browser.close()
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)


def login(page, address):
    from playwright.sync_api import expect

    page.goto(address + "/interviews")
    page.get_by_placeholder("请输入用户名").fill("browser-owner")
    page.get_by_placeholder("至少 6 位").fill("synthetic-test-password")
    page.locator('form button[type="submit"]').click()
    expect(page).to_have_url(address + "/today")
    page.goto(address + "/interviews")
    expect(page.get_by_role("heading", name="面试准备", exact=True)).to_be_visible()


def fill_invitation(page):
    form = page.get_by_role("form", name="记录面试邀请")
    form.get_by_label("公司", exact=True).fill("Browser Fixture Company")
    form.get_by_label("岗位", exact=True).fill("Backend Engineer")
    form.get_by_label("开始时间（含时区）", exact=True).fill(
        "2026-10-01T14:00:00+08:00"
    )
    form.get_by_label("时间所属时区", exact=True).fill("Asia/Shanghai")
    form.get_by_label("原始时间描述", exact=True).fill("10月1日14:00 上海时间")
    return form


def test_real_browser_response_loss_refresh_reads_receipt_without_reposting(
    browser_app,
):
    from playwright.sync_api import expect

    address, context, factory = browser_app
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    login(page, address)
    form = fill_invitation(page)
    commits = []

    def lose_response(route):
        response = route.fetch()  # Real POST completes on the real server FIRST.
        assert response.status == 200, response.text()
        commits.append(response.json()["operation_id"])
        route.abort("failed")  # Browser never receives the successful response.

    page.route("**/career/interview-invitations/confirm", lose_response)
    form.get_by_role("button", name="确认并保存面试").click()
    expect(form.get_by_role("button", name="重试并核实原请求")).to_be_visible()
    assert len(commits) == 1
    retained = page.evaluate(
        "Object.fromEntries(Object.entries(sessionStorage).filter(([k])=>k.startsWith('ic:invitation-submission:')))"
    )
    assert len(retained) == 1
    assert "Browser Fixture Company" not in str(retained)
    page.reload()
    expect(page).to_have_url(__import__("re").compile(r"/interviews\?interview="))
    expect(
        page.get_by_role("region", name="当前面试交接").get_by_text(
            "Browser Fixture Company · Backend Engineer"
        )
    ).to_be_visible()
    assert len(commits) == 1  # Refresh never repeats the mutation.
    assert (
        page.evaluate(
            "Object.keys(sessionStorage).filter(k=>k.startsWith('ic:invitation-submission:')).length"
        )
        == 0
    )
    with factory() as db:
        assert db.query(InterviewRecord).count() == 1
        assert db.query(NextAction).count() == 0
    assert not errors


def test_real_browser_copilot_preserves_business_url_and_text_mode_needs_no_microphone(
    browser_app,
):
    from playwright.sync_api import expect

    address, context, _ = browser_app
    page = context.new_page()
    page.add_init_script("""(() => {
        window.__microphoneRequests = 0;
        if (navigator.mediaDevices) {
            navigator.mediaDevices.getUserMedia = async () => {
                window.__microphoneRequests++;
                throw new Error('This text-only browser case must never request a microphone');
            };
        }
    })();""")
    login(page, address)
    before = page.url
    page.get_by_role("button", name="打开 Copilot").click()
    expect(page.get_by_role("region", name="页面 Copilot")).to_be_visible()
    assert page.url == before
    page.get_by_role("button", name="关闭 Copilot").click()
    page.goto(address + "/mock")
    expect(page.get_by_text("文字面试", exact=True)).to_be_visible()
    assert page.evaluate("window.__microphoneRequests") == 0
