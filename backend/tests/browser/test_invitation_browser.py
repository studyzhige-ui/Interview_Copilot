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
        # This endpoint creates a resource and correctly returns 201. Always
        # settle the intercepted request, even when asserting its response fails;
        # otherwise the browser hangs and the real failure surfaces at teardown.
        try:
            assert response.status == 201, response.text()
            commits.append(response.json()["operation_id"])
        finally:
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


def test_real_browser_text_interview_refresh_requires_explicit_generation_retry(
    browser_app,
):
    """Production UI/HTTP/SQL with a labeled synthetic model failure and reply."""
    from playwright.sync_api import expect
    from app.models.chat import ConversationMessage
    from app.models.mock_interview_runtime import MockInterviewRuntime
    from app.career.application.resumes.resume_artifact_service import (
        create_resume_artifact,
    )

    address, context, factory = browser_app
    with factory() as db:
        owner = db.query(User).filter_by(username="browser-owner").one()
        create_resume_artifact(
            db,
            user_pk=owner.id,
            operation_key="browser-synthetic-resume",
            title="合成测试简历",
            file_asset_id=None,
            raw_text="合成测试履历：负责 Python 后端与缓存接口。不包含真实个人资料。",
            make_default=True,
        )
        db.commit()

    page = context.new_page()
    page.on("dialog", lambda dialog: dialog.accept())
    errors, answer_requests = [], []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "request",
        lambda request: (
            answer_requests.append(request.post_data_json)
            if request.method == "POST" and request.url.endswith("/answer")
            else None
        ),
    )
    page.add_init_script("""(() => {
        window.__microphoneRequests = 0;
        if (navigator.mediaDevices) navigator.mediaDevices.getUserMedia = async () => {
            window.__microphoneRequests++;
            throw new Error('Text-only test must not open a microphone');
        };
    })();""")
    login(page, address)
    page.goto(address + "/mock")
    page.get_by_role("button", name="粘贴文本", exact=True).click()
    page.get_by_placeholder("把 JD 全文粘贴到这里…（≥ 20 字才算有效）").fill(
        "合成岗位：Python 后端工程师，负责接口、事务、缓存与可观察性。"
    )
    page.get_by_role("button", name="开始模拟面试", exact=True).click()
    expect(
        page.get_by_text(
            "你好，我们开始吧。先请你结合目标岗位做一个简单的自我介绍。", exact=True
        )
    ).to_be_visible()
    answer = "合成回答：我负责缓存接口，只测量了延迟，没有验证业务成效。"
    page.get_by_placeholder("输入你的回答，Ctrl+Enter 提交").fill(answer)
    page.get_by_role("button", name="提交", exact=True).click()
    expect(
        page.get_by_role("button", name="重试生成下一题", exact=True)
    ).to_be_visible()
    assert len(answer_requests) == 1
    original = dict(answer_requests[0])
    page.get_by_role("button", name="重新连接", exact=True).click()
    expect(
        page.get_by_role("button", name="重试生成下一题", exact=True)
    ).to_be_visible()
    assert len(answer_requests) == 1

    page.reload()  # A real reload discards all component state.
    page.get_by_role("button", name="继续", exact=True).click()
    expect(page.get_by_text(answer, exact=True)).to_be_visible()
    expect(
        page.get_by_role("button", name="重试生成下一题", exact=True)
    ).to_be_visible()
    assert len(answer_requests) == 1
    expect(page.get_by_role("button", name="提交", exact=True)).to_be_disabled()
    page.get_by_role("button", name="重试生成下一题", exact=True).click()
    expect(
        page.get_by_text("合成测试追问：请说明你如何验证缓存优化的效果？", exact=True)
    ).to_be_visible()
    assert len(answer_requests) == 2
    # Reconciliation reuses the old identity only for reads. A deliberately
    # requested new generation must not reuse an unresolved intent (which the
    # backend correctly refuses to dispatch again).
    retry = answer_requests[1]
    assert retry["request_id"] != original["request_id"]
    assert {k: v for k, v in retry.items() if k != "request_id"} == {
        k: v for k, v in original.items() if k != "request_id"
    }
    assert page.evaluate("window.__microphoneRequests") == 0
    with factory() as db:
        record = db.query(InterviewRecord).filter_by(source="mock").one()
        runtime = (
            db.query(MockInterviewRuntime)
            .filter_by(interview_record_id=record.id)
            .one()
        )
        messages = (
            db.query(ConversationMessage)
            .filter_by(conversation_id=runtime.conversation_id)
            .order_by(ConversationMessage.seq)
            .all()
        )
        assert [message.role for message in messages] == [
            "assistant",
            "user",
            "assistant",
        ]
        assert messages[1].content == answer
        assert runtime.current_stage_key == "resume_project_deep_dive"
        assert runtime.answer_claimed_at is None
        from app.models.mock_answer_submission import MockAnswerSubmission

        receipts = {
            row.request_id: row
            for row in db.query(MockAnswerSubmission).filter_by(record_id=record.id)
        }
        assert set(receipts) == {original["request_id"], retry["request_id"]}
        previous, completed = (
            receipts[original["request_id"]],
            receipts[retry["request_id"]],
        )
        assert previous.status == "unknown" and previous.response_json is None
        assert completed.status == "completed"
        assert completed.response_json["message"]["id"] == messages[-1].id
        assert (
            previous.question_message_id
            == completed.question_message_id
            == original["question_message_id"]
        )
    assert not errors
