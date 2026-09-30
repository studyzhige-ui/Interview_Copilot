"""Production frontend acceptance against real HTTP, auth and isolated PostgreSQL.

Accounts and content are synthetic. No live Supabase, paid model, microphone,
mailbox or external integration is exercised. Screenshots are review evidence,
not an assertion that visual quality was automatically approved.
"""

import json
from pathlib import Path

from app.core.security import get_password_hash
from app.models.user import User
from tests.browser.test_invitation_browser import (
    browser_app as browser_app_fixture,
    database,  # noqa: F401
    fresh_pg_db,  # noqa: F401
    login,
    pytestmark as browser_marks,
)

browser_app = browser_app_fixture
pytestmark = browser_marks

EVIDENCE = Path("test-results/frontend-acceptance")
ROUTES = [
    "/today",
    "/interviews",
    "/activity",
    "/review",
    "/mock",
    "/general-chat",
    "/history",
    "/persistent-tasks",
    "/analytics",
    "/career-profile",
    "/career-process",
    "/career-insights",
    "/artifacts",
    "/library",
    "/models",
    "/plugins",
    "/settings/personalization",
    "/me",
]


def snapshot(page, name):
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(EVIDENCE / f"{name}.png"), full_page=True)


def test_all_primary_routes_desktop_and_mobile_real_http(browser_app):
    from playwright.sync_api import expect

    address, context, _ = browser_app
    page = context.new_page()
    errors, server_errors, observations = [], [], []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "response",
        lambda response: (
            server_errors.append({"url": response.url, "status": response.status})
            if response.status >= 500
            else None
        ),
    )
    login(page, address)
    for size in [{"width": 1440, "height": 1000}, {"width": 390, "height": 844}]:
        page.set_viewport_size(size)
        for route in ROUTES:
            page.goto(address + route)
            expect(page.locator("#workspace-content")).to_be_visible()
            page.wait_for_load_state("networkidle")
            snapshot(page, f"{size['width']}-{route.strip('/').replace('/', '-')}")
            observations.append(
                {
                    "route": route,
                    "viewport": size,
                    "layout": page.evaluate("""() => ({
                    width: innerWidth, bodyWidth: document.body.scrollWidth,
                    mainWidth: document.querySelector('main').clientWidth,
                    mainScrollWidth: document.querySelector('main').scrollWidth,
                    text: document.querySelector('main').innerText.slice(0, 600)
                })"""),
                }
            )
    (EVIDENCE / "route-observations.json").write_text(
        json.dumps(
            {
                "boundary": "real HTTP/auth/PostgreSQL; synthetic users; no live providers",
                "observations": observations,
                "page_errors": errors,
                "server_errors": server_errors,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    assert not errors
    assert not server_errors
    for item in observations:
        assert item["layout"]["text"].strip(), item
        assert item["layout"]["bodyWidth"] <= item["viewport"]["width"] + 2, item
        assert item["layout"]["mainScrollWidth"] <= item["layout"]["mainWidth"] + 2, (
            item
        )


def test_opportunity_modal_keyboard_repeated_open_and_account_isolation(browser_app):
    from playwright.sync_api import expect

    address, context, factory = browser_app
    with factory() as db:
        db.add(
            User(
                username="browser-second",
                hashed_password=get_password_hash("synthetic-test-password"),
            )
        )
        db.commit()
    page = context.new_page()
    login(page, address)
    page.goto(address + "/career-process")
    opener = page.get_by_role("button", name="添加机会", exact=True)
    opener.click()
    modal = page.get_by_role("dialog", name="添加求职机会")
    expect(modal.get_by_label("公司", exact=True)).to_be_focused()
    expect(modal.get_by_role("button", name="开始跟进")).to_be_disabled()
    for _ in range(18):
        page.keyboard.press("Tab")
        assert page.evaluate("!!document.activeElement.closest('[role=dialog]')")
    for _ in range(18):
        page.keyboard.press("Shift+Tab")
        assert page.evaluate("!!document.activeElement.closest('[role=dialog]')")
    page.keyboard.press("Escape")
    expect(modal).not_to_be_visible()
    expect(opener).to_be_focused()
    opener.click()
    modal.get_by_label("公司", exact=True).fill("Synthetic Acceptance Company")
    modal.get_by_label("岗位", exact=True).fill("Synthetic Backend Engineer")
    modal.get_by_placeholder("例如：在公司官网看到岗位，准备本周申请").fill(
        "Synthetic user-confirmed opportunity for browser acceptance only"
    )
    snapshot(page, "opportunity-modal-desktop")
    with page.expect_response(
        lambda response: (
            response.request.method == "POST"
            and response.url.endswith("/career-process/opportunities")
        )
    ) as created:
        modal.get_by_role("button", name="开始跟进").click()
    assert created.value.status == 201, created.value.text()
    expect(modal).not_to_be_visible()
    expect(
        page.get_by_text("Synthetic Acceptance Company", exact=True).first
    ).to_be_visible()
    page.reload()
    expect(
        page.get_by_text("Synthetic Acceptance Company", exact=True).first
    ).to_be_visible()
    snapshot(page, "opportunity-created")
    page.get_by_role("button", name="账户菜单").click()
    page.get_by_role("button", name="登出", exact=True).click()
    expect(page).to_have_url(address + "/auth")
    page.go_back()
    expect(page).to_have_url(address + "/auth")
    page.get_by_placeholder("请输入用户名").fill("browser-second")
    page.get_by_placeholder("至少 6 位").fill("synthetic-test-password")
    page.locator('form button[type="submit"]').click()
    expect(page).to_have_url(address + "/today")
    page.goto(address + "/career-process")
    page.wait_for_load_state("networkidle")
    expect(page.get_by_text("Synthetic Acceptance Company", exact=True)).to_have_count(
        0
    )
    snapshot(page, "second-account-no-first-account-data")


def test_loading_failure_retry_and_interrupted_navigation(browser_app):
    from playwright.sync_api import expect

    address, context, _ = browser_app
    page = context.new_page()
    login(page, address)
    # This test alone injects a transport failure. Normal reads and retries
    # still use the production API; no business success response is fabricated.
    page.route("**/api/v1/workspace", lambda route: route.abort("failed"))
    page.goto(address + "/today")
    expect(page.get_by_text("暂时无法读取协作进度", exact=True)).to_be_visible()
    snapshot(page, "today-transport-error")
    page.unroute("**/api/v1/workspace")
    page.get_by_role("button", name="重新加载", exact=True).first.click()
    expect(page.get_by_text("暂时无法读取协作进度", exact=True)).not_to_be_visible()
    page.get_by_role("button", name="打开 Copilot", exact=True).click()
    expect(page.get_by_role("region", name="页面 Copilot")).to_be_visible()
    page.get_by_role("button", name="关闭 Copilot", exact=True).click()
    expect(page.get_by_role("region", name="页面 Copilot")).not_to_be_visible()
    expect(page).to_have_url(address + "/today")
    page.get_by_role("button", name="打开 Copilot", exact=True).click()
    expect(page.get_by_role("region", name="页面 Copilot")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.get_by_role("region", name="页面 Copilot")).not_to_be_visible()
    expect(page).to_have_url(address + "/today")


def test_deleted_conversation_and_older_review_deep_link_regressions(browser_app):
    from datetime import timedelta
    from playwright.sync_api import expect
    from app.db.types import utc_now
    from app.models.chat import Conversation
    from app.models.interview_record import InterviewRecord
    from app.models.interview_transcript import InterviewTranscript

    address, context, factory = browser_app
    with factory() as db:
        owner = db.query(User).filter_by(username="browser-owner").one()
        first = Conversation(
            user_id=owner.id, title="Synthetic conversation one", type="general"
        )
        second = Conversation(
            user_id=owner.id, title="Synthetic conversation two", type="general"
        )
        db.add_all([first, second])
        now = utc_now()
        for index in range(51):
            db.add(
                InterviewRecord(
                    id=f"ir_browser_{index:03d}",
                    user_id=owner.id,
                    source="upload",
                    title=f"Synthetic review {index:03d}",
                    status="completed",
                    transcript_id=f"it_browser_{index:03d}",
                    created_at=now - timedelta(days=index),
                )
            )
        db.flush()
        db.add_all(
            InterviewTranscript(
                id=f"it_browser_{index:03d}",
                record_id=f"ir_browser_{index:03d}",
                user_id=owner.id,
                provider="synthetic_acceptance",
                text="Synthetic interview transcript for navigation acceptance.",
                status="ready",
            )
            for index in range(51)
        )
        db.commit()
        first_id, second_id = first.id, second.id
    page = context.new_page()
    login(page, address)
    page.goto(address + f"/general-chat?session={first_id}")
    row = page.get_by_text("Synthetic conversation one", exact=True).first.locator("..")
    row.hover()
    row.get_by_title("删除", exact=True).click()
    modal = page.get_by_role("dialog", name="删除对话")
    expect(modal.get_by_role("button", name="删除", exact=True)).to_be_enabled()
    modal.get_by_role("button", name="删除", exact=True).click()
    expect(modal).not_to_be_visible()
    expect(page.get_by_text("Synthetic conversation one", exact=True)).to_have_count(0)
    assert first_id not in page.url
    expect(
        page.get_by_text("Synthetic conversation two", exact=True).first
    ).to_be_visible()
    with factory() as db:
        assert db.get(Conversation, first_id) is None
        assert db.get(Conversation, second_id) is not None
    snapshot(page, "conversation-deleted-selection-recovered")
    page.goto(address + "/review?id=ir_browser_050")
    expect(
        page.get_by_role("heading", name="Synthetic review 050", exact=True)
    ).to_be_visible()
    snapshot(page, "review-older-than-first-page")
    page.reload()
    expect(
        page.get_by_role("heading", name="Synthetic review 050", exact=True)
    ).to_be_visible()
    page.goto(address + "/review?id=ir_browser_missing")
    expect(page.get_by_text("面试记录暂不可用", exact=True)).to_be_visible()
    expect(
        page.get_by_role("heading", name="Synthetic review 000", exact=True)
    ).to_have_count(0)
    snapshot(page, "review-missing-target-not-wrong-record")
