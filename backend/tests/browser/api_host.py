"""Serve the production app + built frontend on loopback against a fresh test DB.

No production startup/HTTP/auth/Operation handler is replaced. External model
transport is forbidden. Mock-interview model outputs below are explicitly synthetic;
all real HTTP/auth/domain/SQL and structured-output validation remain in use.
"""

import os
from pathlib import Path
from urllib.parse import urlparse

if os.environ.get("IC_BROWSER_TEST") != "1":
    raise RuntimeError("browser host is test-only")
url = urlparse(os.environ["DATABASE_URL"])
if not url.path.startswith("/ic_mig_test_") or url.hostname not in {
    "localhost",
    "127.0.0.1",
    "::1",
}:
    raise RuntimeError("browser host requires an isolated loopback test database")

from app.core.model_provider_adapter import ModelProviderAdapter  # noqa: E402


async def reject_live_model(*_args, **_kwargs):
    raise RuntimeError(
        "live model calls are forbidden in this deterministic browser campaign"
    )


ModelProviderAdapter.start_stream = reject_live_model

# This replaces only the paid mock-model adapter. It is guarded above and never
# installed by the production app. The scenario tests behavior, not model quality.
import json  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from app.interviews.application import mock_interview_service  # noqa: E402


class FixtureInterviewModel:
    context_window = 128_000
    max_tokens = 4096

    def __init__(self):
        self.turn_calls = 0

    def complete(self, prompt, **kwargs):
        return SimpleNamespace(
            text=json.dumps(
                {
                    "guidance": {
                        stage["key"]: f"合成测试引导：{stage['title']}。"
                        for stage in mock_interview_service.BASE_INTERVIEW_STAGES
                    }
                },
                ensure_ascii=False,
            )
        )

    async def acomplete(self, prompt, **kwargs):
        self.turn_calls += 1
        if self.turn_calls == 1:
            raise TimeoutError("synthetic response loss; never a live provider")
        return SimpleNamespace(
            text=json.dumps(
                {
                    "message": "合成测试追问：请说明你如何验证缓存优化的效果？",
                    "next_stage_key": "resume_project_deep_dive",
                    "ready_to_finish": False,
                },
                ensure_ascii=False,
            )
        )


fixture_interview_model = FixtureInterviewModel()
mock_interview_service.get_llm_for_role = lambda *_a, **_k: fixture_interview_model

from app.main import app  # noqa: E402
from starlette.exceptions import HTTPException  # noqa: E402
from starlette.staticfiles import StaticFiles  # noqa: E402


class SpaFiles(StaticFiles):
    async def get_response(self, path, scope):
        if path.startswith("api/"):
            raise HTTPException(404)
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or Path(path).suffix:
                raise
            return await super().get_response("index.html", scope)


dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"
app.mount("/", SpaFiles(directory=dist, html=True), name="browser-test-spa")
