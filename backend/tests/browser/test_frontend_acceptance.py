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
    safe_response_failure,
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


def capture_workspace_scroll(page, name, selector="#workspace-content"):
    """Capture the internal scroll owner; full_page only captures document scroll."""
    owner = page.locator(selector)
    metrics = owner.evaluate(
        "el => ({height: el.clientHeight, total: el.scrollHeight})"
    )
    bottom = max(0, metrics["total"] - metrics["height"])
    step = max(1, int(metrics["height"] * 0.8))
    offsets = list(range(step, bottom, step)) + ([bottom] if bottom else [])
    for index, offset in enumerate(offsets, 1):
        owner.evaluate("(el, y) => { el.scrollTop = y; }", offset)
        snapshot(page, f"{name}-scroll-{index:02d}")
    owner.evaluate("el => { el.scrollTop = 0; }")
    return {**metrics, "owner": selector, "captured_offsets": [0, *offsets]}


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
            name = f"{size['width']}-{route.strip('/').replace('/', '-')}"
            snapshot(page, name)
            # Plugin marketplace intentionally owns an inner full-height scroller.
            # Capturing the shell alone misses lower cards on narrow viewports.
            scroll_owner = (
                "#workspace-content > .overflow-auto"
                if route == "/plugins"
                else "#workspace-content"
            )
            scroll_coverage = capture_workspace_scroll(page, name, scroll_owner)
            if size["width"] == 390 and route == "/plugins":
                assert len(scroll_coverage["captured_offsets"]) > 1
            if size["width"] == 390 and route == "/me":
                identity = (
                    page.get_by_text("@browser-owner", exact=True)
                    .locator("..")
                    .bounding_box()
                )
                save = page.get_by_role(
                    "button", name="保存修改", exact=True
                ).bounding_box()
                assert identity and save
                assert save["y"] >= identity["y"] + identity["height"] - 1, (
                    identity,
                    save,
                )
            if size["width"] == 390 and route == "/career-process":
                for label in ["刷新", "检查重复", "记录新岗位面试", "添加机会"]:
                    box = page.get_by_role(
                        "button", name=label, exact=True
                    ).first.bounding_box()
                    assert box and box["height"] <= 38, (label, box)

            observations.append(
                {
                    "route": route,
                    "viewport": size,
                    "scroll_coverage": scroll_coverage,
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
    page.set_viewport_size({"width": 390, "height": 844})
    snapshot(page, "opportunity-modal-mobile-top")
    modal.locator(".overflow-auto").evaluate(
        "el => { el.scrollTop = el.scrollHeight; }"
    )
    snapshot(page, "opportunity-modal-mobile-bottom")
    expect(modal.get_by_role("button", name="开始跟进")).to_be_in_viewport()
    page.set_viewport_size({"width": 1280, "height": 720})
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


def test_local_file_avatar_upload_reload_download_and_owner_usage(browser_app):
    """Real local capability PUT/media GET and authenticated owner download, no S3."""
    import base64
    from playwright.sync_api import expect

    address, context, _ = browser_app
    page = context.new_page()
    login(page, address)
    page.goto(address + "/me")
    expect(page.get_by_role("region", name="文件存储")).to_be_visible()
    expect(page.get_by_text("新文件保存位置：本地文件存储", exact=True)).to_be_visible()
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFklEQVR4nGM0SglgYGBgYmBgYGBgAAAK1ADqrdxXQwAAAABJRU5ErkJggg=="
    )
    puts = []
    page.on(
        "request",
        lambda request: puts.append(request) if request.method == "PUT" else None,
    )
    with page.expect_response(
        lambda response: response.url.endswith("/file-assets/upload-url")
    ) as reserved:
        with page.expect_response(
            lambda response: response.url.endswith("/auth/me/avatar")
        ) as avatar:
            page.locator('input[type="file"]').set_input_files(
                {
                    "name": "synthetic-avatar.png",
                    "mimeType": "image/png",
                    "buffer": png,
                }
            )
    assert reserved.value.ok, safe_response_failure(reserved.value)
    assert avatar.value.ok, safe_response_failure(avatar.value)
    asset_id = reserved.value.json()["file_asset_id"]
    assert len(puts) == 1 and "authorization" not in puts[0].headers
    image = page.get_by_alt_text("头像", exact=True)
    expect(image).to_be_visible()
    expect(image).to_have_js_property("complete", True)
    expect(image).to_have_js_property("naturalWidth", 2)
    expect(
        page.get_by_role("region", name="文件存储").get_by_text("1 个", exact=True)
    ).to_be_visible()
    page.reload()
    expect(page.get_by_alt_text("头像", exact=True)).to_have_js_property(
        "naturalWidth", 2
    )
    expect(
        page.get_by_role("region", name="文件存储").get_by_text("1 个", exact=True)
    ).to_be_visible()
    snapshot(page, "local-file-avatar-persisted-and-owner-usage")
    page.get_by_role("region", name="文件存储").scroll_into_view_if_needed()
    snapshot(page, "local-file-owner-storage-summary")
    page.set_viewport_size({"width": 390, "height": 844})
    page.get_by_role("region", name="文件存储").scroll_into_view_if_needed()
    snapshot(page, "local-file-mobile-storage-summary")
    download = page.evaluate(
        """async (id) => {
        const response = await fetch('/api/v1/file-assets/' + encodeURIComponent(id) + '/download', {
            headers: { Authorization: 'Bearer ' + localStorage.getItem('access_token') }
        });
        return {status: response.status, bytes: Array.from(new Uint8Array(await response.arrayBuffer()))};
    }""",
        asset_id,
    )
    assert download["status"] == 200
    assert bytes(download["bytes"]) == png


def test_real_expired_answer_audio_renews_once_without_autoplay(
    browser_app, monkeypatch
):
    """Real expired capability + real WAV decoding; only initial detail URL is aged."""
    import io
    import wave
    from playwright.sync_api import expect
    from app.core.config import settings
    from app.files.application.storage_access import asset_url
    from app.models.file_asset import FileAsset
    from app.models.interview_record import InterviewRecord
    from app.models.interview_qa import InterviewQA

    address, context, factory = browser_app
    page = context.new_page()
    login(page, address)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(b"\0\0" * 16000)
    payload = buffer.getvalue()
    asset_id = page.evaluate(
        """async (bytes) => {
        const headers = {Authorization: 'Bearer ' + localStorage.getItem('access_token')};
        const reservation = await fetch('/api/v1/file-assets/upload-url', {
            method: 'POST', headers: {...headers, 'Content-Type': 'application/json'},
            body: JSON.stringify({purpose: 'mock_audio_clip', filename: 'synthetic.wav', content_type: 'audio/wav', size_bytes: bytes.length})
        });
        if (!reservation.ok) throw new Error('Synthetic audio reservation failed');
        const asset = await reservation.json();
        const upload = await fetch(asset.upload_url, {method: 'PUT', headers: {'Content-Type': 'audio/wav'}, body: new Uint8Array(bytes)});
        if (!upload.ok) throw new Error('Synthetic audio upload failed');
        const confirmed = await fetch('/api/v1/file-assets/' + asset.file_asset_id + '/confirm', {method: 'POST', headers});
        if (!confirmed.ok) throw new Error('Synthetic audio confirmation failed');
        return asset.file_asset_id;
    }""",
        list(payload),
    )
    record_id = "ir_browser_audio_expiry"
    with factory() as db:
        owner = db.query(User).filter_by(username="browser-owner").one()
        db.add(
            InterviewRecord(
                id=record_id,
                user_id=owner.id,
                source="mock",
                status="review_ready",
                title="Synthetic audio renewal",
            )
        )
        db.flush()
        db.add(
            InterviewQA(
                record_id=record_id,
                question="Synthetic question",
                answer="Synthetic answer",
                answer_input_mode="voice",
                answer_audio_file_asset_id=asset_id,
            )
        )
        db.commit()
        asset = db.get(FileAsset, asset_id)
        # The browser host has this isolated synthetic key, never a user secret.
        # Expire this one fixture token; production TTL/config is never changed.
        with monkeypatch.context() as patch:
            patch.setattr(
                settings,
                "SECRET_KEY",
                "isolated-browser-secret-not-production-32-bytes",
            )
            expired = asset_url(asset, owner=owner, operation="read", expiration=-1)
    detail_reads = []
    media_statuses = []

    def initial_expired_detail(route):
        response = route.fetch()
        assert response.status == 200
        body = response.json()
        detail_reads.append(body["id"])
        if len(detail_reads) == 1:
            body["qa"][0]["answer_audio_url"] = expired
        route.fulfill(response=response, json=body)

    page.route(f"**/api/v1/interview-records/{record_id}", initial_expired_detail)
    page.on(
        "response",
        lambda response: (
            media_statuses.append(response.status)
            if f"/file-assets/{asset_id}/content?" in response.url
            else None
        ),
    )
    page.goto(address + f"/review?id={record_id}")
    page.get_by_role("button", name="QA 对", exact=True).click()
    player = page.get_by_label("回答原录音", exact=True)
    expect(player).to_have_attribute("src", expired)
    # Fetch metadata without starting playback; expired GET genuinely returns403.
    player.evaluate("audio => { audio.preload = 'metadata'; audio.load(); }")
    expect(page.get_by_text("播放链接已刷新，请重新播放", exact=True)).to_be_visible()
    expect(player).not_to_have_attribute("src", expired)
    assert detail_reads == [record_id, record_id]
    assert 403 in media_statuses
    assert player.evaluate("audio => audio.paused")
    player.evaluate("audio => { audio.preload = 'auto'; audio.load(); }")
    page.wait_for_function("""() => {
        const audio = document.querySelector('audio[aria-label="回答原录音"]');
        return audio && audio.readyState >= 2;
    }""")
    assert player.evaluate("audio => audio.duration") == 1
    assert player.evaluate("audio => audio.paused")
    assert any(status in {200, 206} for status in media_statuses)
    player_box = player.bounding_box()
    card_box = player.locator("xpath=ancestor::article[1]").bounding_box()
    assert player_box and card_box
    assert player_box["x"] + player_box["width"] <= card_box["x"] + card_box["width"], (
        player_box,
        card_box,
    )
    snapshot(page, "expired-answer-audio-authorized-renewal-no-autoplay")
