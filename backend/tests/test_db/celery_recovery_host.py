"""Isolated real Celery host: only model transport and heavyweight warmup are faked.

Never import this module from production. The parent tests provision a throwaway
PostgreSQL database and a unique Redis namespace. No live model can be invoked.
"""

import importlib
import json
import os
from pathlib import Path
import time
from urllib.parse import urlparse

config_path = os.environ.get("IC_CELERY_TEST_CONFIG")
if not config_path:
    raise RuntimeError("isolated Celery test configuration is required")
config = json.loads(Path(config_path).read_text())
url = urlparse(os.environ["DATABASE_URL"])
if not url.path.startswith("/ic_mig_test_") or url.hostname not in {
    "localhost",
    "127.0.0.1",
    "::1",
}:
    raise RuntimeError("refusing a non-isolated test database")
if not config["queue"].startswith("ic-recovery-test-"):
    raise RuntimeError("refusing a non-isolated queue")

from app.core.model_catalog import ModelProfile  # noqa: E402
from app.core.model_provider_adapter import (  # noqa: E402
    ModelProviderAdapter,
    ProviderStreamEvent,
    ProviderUsage,
)

profile = ModelProfile(
    id="fixture/recovery",
    provider="fixture",
    display_name="Offline fixture",
    model="recovery",
    api_base="http://127.0.0.1:1",
    api_key_env="IC_UNUSED_KEY",
    supports_function_calling=True,
)


# These seams replace external inference, not the durable dispatcher, strategy,
# policy, tool invocation, transaction, transcript, or event buffer.
def fixture_client(*_args, **_kwargs):
    return object(), profile


async def fixture_stream(self, request):
    async def events():
        yield ProviderStreamEvent(text_delta="已按保存的决定核实面试邀请。")
        yield ProviderStreamEvent(usage=ProviderUsage(100, 20), stop_reason="stop")

    return events()


from app.conversation import agent_strategy  # noqa: E402

agent_strategy.build_async_openai_client_for_role = fixture_client
ModelProviderAdapter.start_stream = fixture_stream
queue_module = importlib.import_module("app.task_queue.celery_app")
queue_module._ensure_worker_runtime = lambda **_kwargs: None
celery_app = queue_module.celery_app
celery_app.conf.update(
    task_default_queue=config["queue"],
    task_routes={"tasks.process_conversation_turn": {"queue": config["queue"]}},
    broker_transport_options={
        "visibility_timeout": 3700,
        "global_keyprefix": config["queue"] + ":",
    },
    result_backend_transport_options={"global_keyprefix": config["queue"] + ":"},
)


def stop_at_boundary():
    Path(config["boundary_file"]).write_text(str(os.getpid()))
    # The parent sends SIGKILL to this actual Celery worker, so no Python
    # cancellation/finally/rollback can substitute for process-death recovery.
    while True:
        time.sleep(0.1)


if config.get("phase") == "verifying":
    from app.career.application import interview_invitation_operations as operations

    original = operations._verification

    def verifying(*args, **kwargs):
        stop_at_boundary()
        return original(*args, **kwargs)

    operations._verification = verifying
elif config.get("phase") == "committed":
    from app.agent_runtime.tools import interview_invitation as tool

    handler_name = (
        "_confirm_asserted_sync"
        if config.get("origin") == "asserted"
        else "_review_candidate_sync"
    )
    original = getattr(tool, handler_name)

    def committed(*args, **kwargs):
        result = original(*args, **kwargs)
        if result.get("error"):
            raise RuntimeError(result)
        stop_at_boundary()
        return result

    setattr(tool, handler_name, committed)
