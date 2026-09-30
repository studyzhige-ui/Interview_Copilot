"""Run the independent Linux/WSL2 model broker, or query its content-free status."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import signal
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.local_inference.config import BrokerConfig  # noqa: E402
from app.local_inference.client import Client  # noqa: E402
from app.local_inference.server import Server  # noqa: E402


async def run(config):
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stop.set)
    server = Server(config)
    try:
        await server.start()
        print('{"status":"listening","model_quality_validated":false}', flush=True)
        await stop.wait()
    finally:
        await server.close()
        for signum in (signal.SIGTERM, signal.SIGINT):
            loop.remove_signal_handler(signum)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args(argv)
    config = BrokerConfig.load(args.config)
    if args.status:
        print(json.dumps(asyncio.run(Client(config.socket_path).status())))
    else:
        asyncio.run(run(config))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, TypeError):
        print('{"status":"failed","code":"local_broker_not_available"}')
        raise SystemExit(2)
