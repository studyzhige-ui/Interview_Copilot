"""Use the installation's actual auth mode; never inject a browser token."""

import os
import pytest


@pytest.fixture(scope="module")
def acceptance_login():
    def login(client):
        config = client.get("/api/v1/auth/config")
        assert config.status_code == 200
        if config.json()["provider"] == "supabase":
            response = client.post(
                "/api/v1/auth/local-unlock",
                json={
                    "email": os.environ["IC_ACCEPTANCE_EMAIL"],
                    "password": os.environ["IC_ACCEPTANCE_PASSWORD"],
                },
            )
        else:
            response = client.post(
                "/api/v1/auth/login",
                data={
                    "username": os.environ["IC_ACCEPTANCE_USERNAME"],
                    "password": os.environ["IC_ACCEPTANCE_PASSWORD"],
                },
            )
        assert response.status_code == 200, response.text
        return response.json()

    return login


@pytest.fixture
def acceptance_browser_login():
    def login(page, origin):
        config = page.request.get(origin + "/api/v1/auth/config")
        assert config.ok
        page.goto(origin + "/auth")
        if config.json()["provider"] == "supabase":
            page.get_by_role("button", name="离线时使用本地解锁", exact=True).click()
            page.get_by_label("邮箱", exact=True).fill(
                os.environ["IC_ACCEPTANCE_EMAIL"]
            )
            page.get_by_label("独立的本地解锁密码", exact=True).fill(
                os.environ["IC_ACCEPTANCE_PASSWORD"]
            )
            page.get_by_role("button", name="本地解锁", exact=True).click()
        else:
            page.get_by_placeholder("请输入用户名").fill(
                os.environ["IC_ACCEPTANCE_USERNAME"]
            )
            page.get_by_placeholder("至少 6 位").fill(
                os.environ["IC_ACCEPTANCE_PASSWORD"]
            )
            page.locator("form button[type=submit]").click()
        page.wait_for_url("**/today")

    return login
