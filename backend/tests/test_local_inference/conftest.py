from pathlib import Path
import sys
import pytest

from app.local_inference.config import BrokerConfig, ModelSpec
from app.local_inference.client import make_request


@pytest.fixture
def specs(tmp_path):
    weights = tmp_path / "weights"
    weights.mkdir()
    return (
        ModelSpec(
            "embedding",
            "test/embedding",
            str(weights),
            sys.executable,
            dimension=3,
            max_tokens=32,
            reservation_mib=20,
        ),
        ModelSpec(
            "reranking",
            "test/reranking",
            str(weights),
            sys.executable,
            dimension=1,
            max_tokens=32,
            reservation_mib=20,
        ),
    )


@pytest.fixture
def config(tmp_path, specs):
    # Linux limits AF_UNIX path length, including pytest's parent directory.
    import tempfile

    with tempfile.TemporaryDirectory(prefix="ic-") as name:
        root = Path(name)
        yield BrokerConfig(
            str(root / "rpc.sock"),
            str(root / "cache"),
            specs,
            capacity_mib=30,
            max_pending=4,
            idle_seconds=1,
        )


def task(spec, *, priority="interactive", timeout=2, texts=None):
    return make_request(
        spec.role,
        spec.binding,
        "query" if spec.role == "embedding" else "rank",
        texts or ["hello"],
        query="query" if spec.role == "reranking" else "",
        priority=priority,
        timeout=timeout,
    )
