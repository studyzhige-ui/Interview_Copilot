"""Authenticated Chromium navigation against the explicit acceptance stack."""

import os
import uuid
from pathlib import Path

import pytest


def test_authenticated_product_pages(acceptance_browser_login):
    origin = os.environ.get("IC_ACCEPTANCE_BASE_URL")
    if not origin or os.environ.get("IC_RUN_BROWSER") != "1":
        pytest.skip("explicit real stack and browser opt-in required")
    from playwright.sync_api import sync_playwright, expect

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 960})
        errors, server_errors = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "response",
            lambda response: (
                server_errors.append((response.status, response.url))
                if response.status >= 500
                else None
            ),
        )
        acceptance_browser_login(page, origin)
        paths = (
            "today",
            "activity",
            "review",
            "mock",
            "general-chat",
            "history",
            "persistent-tasks",
            "analytics",
            "career-profile",
            "career-process",
            "career-calendar",
            "career-insights",
            "artifacts",
            "library",
            "models",
            "capabilities",
            "plugins",
            "settings/personalization",
            "settings/notifications",
            "me",
        )
        screenshots = Path("output/playwright/release")
        screenshots.mkdir(parents=True, exist_ok=True)
        for path in paths:
            page.goto(origin + "/" + path)
            page.wait_for_load_state("networkidle")
            assert "/auth" not in page.url, path
            expect(page.locator("body")).not_to_be_empty()
            assert len(page.locator("body").inner_text()) > 40, path
            page.screenshot(path=str(screenshots / (path.replace("/", "-") + ".png")))
        page.goto(origin + "/career-calendar?view=calendar&opportunity=scope-fixture")
        page.get_by_role("button", name="行动与提醒", exact=True).click()
        assert "opportunity=scope-fixture" in page.url and "view=actions" in page.url
        page.get_by_role("button", name="日历", exact=True).click()
        assert "opportunity=scope-fixture" in page.url and "view=calendar" in page.url
        browser.close()
        assert not errors, errors
        assert not server_errors, server_errors


def test_settings_forms_persist_after_reload(acceptance_browser_login):
    origin = os.environ.get("IC_ACCEPTANCE_BASE_URL")
    if not origin or os.environ.get("IC_RUN_BROWSER") != "1":
        pytest.skip("explicit real stack and browser opt-in required")
    from playwright.sync_api import sync_playwright, expect

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        acceptance_browser_login(page, origin)
        # Each form is changed through the UI, reloaded, then restored through it.
        cases = (
            ("me", "input[placeholder='给自己起个昵称']", "验收昵称", "保存修改"),
            (
                "settings/personalization",
                "textarea[aria-label='全局协作规则 1']",
                "回答时先解释关键取舍。",
                "保存全局规则",
            ),
            (
                "settings/notifications",
                "input:not([type])",
                "Asia/Tokyo",
                "保存通知设置",
            ),
        )
        try:
            for path, selector, value, button in cases:
                page.goto(origin + "/" + path)
                page.wait_for_load_state("networkidle")
                field = page.locator(selector).first
                previous = field.input_value()
                try:
                    field.fill(value)
                    with page.expect_response(
                        lambda r: (
                            r.request.method in ("PUT", "PATCH") and "/api/v1/" in r.url
                        )
                    ) as saved:
                        page.get_by_role("button", name=button, exact=True).click()
                    assert saved.value.ok, saved.value.status
                    page.reload()
                    expect(page.locator(selector).first).to_have_value(value)
                finally:
                    page.locator(selector).first.fill(previous)
                    with page.expect_response(
                        lambda r: (
                            r.request.method in ("PUT", "PATCH") and "/api/v1/" in r.url
                        )
                    ) as restored:
                        page.get_by_role("button", name=button, exact=True).click()
                    assert restored.value.ok, restored.value.status
                    page.reload()
                    expect(page.locator(selector).first).to_have_value(previous)
        finally:
            browser.close()


def test_invitation_committed_response_loss_recovers_after_reload(
    acceptance_browser_login, acceptance_login
):
    origin = os.environ.get("IC_ACCEPTANCE_BASE_URL")
    if not origin or os.environ.get("IC_RUN_BROWSER") != "1":
        pytest.skip("explicit real stack and browser opt-in required")
    import httpx
    from playwright.sync_api import sync_playwright, expect

    with httpx.Client(base_url=origin, timeout=90) as api:
        token = acceptance_login(api)
        api.headers["Authorization"] = "Bearer " + token["access_token"]
        created = api.post(
            "/api/v1/career-workspace/jobs",
            json={
                "operation_key": uuid.uuid4().hex,
                "company_name": "Response loss fixture",
                "job_title": "Python engineer",
            },
        )
        assert created.status_code == 201
        job = created.json()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            try:
                acceptance_browser_login(page, origin)
                path = origin + f"/career-process?opportunity={job['id']}"
                page.goto(path)
                page.get_by_role("button", name="安排面试", exact=True).click()
                form = page.get_by_role("dialog", name="安排面试")
                form.get_by_label("面试时间（本地时区）").fill("2030-10-15T12:00")
                receipts = []

                def lose_only_the_response(route):
                    result = route.fetch()
                    assert result.ok
                    receipts.append(result.json())
                    route.abort("failed")

                page.route(
                    "**/career/interview-invitations/confirm", lose_only_the_response
                )
                form.get_by_role("button", name="保存面试安排", exact=True).click()
                expect(
                    page.get_by_text("上次安排已经保存，可以直接查看。", exact=True)
                ).to_be_visible()
                page.reload()
                page.get_by_role("button", name="安排面试", exact=True).click()
                screenshots = Path("output/playwright/release")
                screenshots.mkdir(parents=True, exist_ok=True)
                page.screenshot(
                    path=str(screenshots / "invitation-receipt-recovery.png")
                )
                page.get_by_role("button", name="查看已保存安排", exact=True).click()
                expect(page.get_by_role("dialog", name="安排面试")).not_to_be_visible()
                expect(
                    page.get_by_role("link", name="查看面试与复盘 ↗", exact=True)
                ).to_be_visible()
                current = api.get(f"/api/v1/career-workspace/jobs/{job['id']}")
                assert current.status_code == 200
                interviews = current.json()["interviews"]
                assert len(receipts) == 1 and len(interviews) == 1
                assert interviews[0]["id"] == receipts[0]["interview"]["id"]
            finally:
                browser.close()
