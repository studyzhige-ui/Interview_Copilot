"""Serve the production app + built frontend on loopback against a fresh test DB.

No production startup/HTTP/auth/Operation handler is replaced. External model
transport is forbidden in this browser campaign. Run via the guarded test fixture.
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
