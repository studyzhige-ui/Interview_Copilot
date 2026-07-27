"""Run scoped concurrency, Redis-outage, and worker-kill recovery drills."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _claim_child(turn_id: str) -> int:
    from app.services.chat.turn_executor import _claim

    claimed = _claim(turn_id)
    print("CLAIMED" if claimed else "NOT_CLAIMED", flush=True)
    if not claimed:
        return 1
    time.sleep(300)
    return 0


def _run_concurrency(conversation_id: str, user_id: int) -> tuple[str, int]:
    from app.db.database import SessionLocal
    from app.models.chat import Conversation
    from app.services.chat.turn_executor import create_turn

    def submit(index: int) -> tuple[str, str]:
        with SessionLocal() as db:
            conversation = db.get(Conversation, conversation_id)
            try:
                turn = create_turn(
                    db,
                    conversation,
                    user_id=user_id,
                    mode="chat",
                    message=f"concurrent drill {index}",
                )
                return "created", turn.id
            except ValueError as exc:
                return "conflict", str(exc)

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(submit, range(8)))
    created = [value for status, value in results if status == "created"]
    conflicts = sum(status == "conflict" for status, _ in results)
    if len(created) != 1 or conflicts != 7:
        raise RuntimeError(f"Unexpected concurrency result: {results}")
    return created[0], conflicts


async def _run_network_outage() -> dict[str, bool]:
    import redis.asyncio as aioredis

    from app.services.chat import turn_event_buffer as buffer_module

    name = f"interview-copilot-redis-drill-{uuid.uuid4().hex[:8]}"
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "-p",
            "127.0.0.1::6379",
            "redis:alpine",
        ],
        check=True,
        capture_output=True,
    )
    client = None
    try:
        mapping = subprocess.run(
            ["docker", "port", name, "6379/tcp"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        port = int(mapping.rsplit(":", 1)[1])
        client = aioredis.from_url(
            f"redis://127.0.0.1:{port}/0",
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        buffer_module.redis_client = client
        await buffer_module.turn_event_buffer.append("drill", '{"type":"text"}')
        before = bool(await client.ping())

        subprocess.run(["docker", "stop", name], check=True, capture_output=True)
        unavailable = False
        try:
            await buffer_module.turn_event_buffer.append("drill", '{"type":"text"}')
        except Exception:  # noqa: BLE001 - outage is the expected result
            unavailable = True

        subprocess.run(["docker", "start", name], check=True, capture_output=True)
        await client.aclose()
        mapping = subprocess.run(
            ["docker", "port", name, "6379/tcp"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        port = int(mapping.rsplit(":", 1)[1])
        client = aioredis.from_url(
            f"redis://127.0.0.1:{port}/0",
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        buffer_module.redis_client = client
        recovered = False
        for _ in range(20):
            try:
                recovered = bool(await client.ping())
                if recovered:
                    break
            except Exception:  # noqa: BLE001 - container is still starting
                await asyncio.sleep(0.25)
        if not (before and unavailable and recovered):
            raise RuntimeError(
                "Redis outage/recovery drill did not reach every state: "
                f"before={before}, unavailable={unavailable}, recovered={recovered}"
            )
        return {
            "available_before": before,
            "failure_detected": unavailable,
            "recovered": recovered,
        }
    finally:
        if client is not None:
            await client.aclose()
        subprocess.run(
            ["docker", "rm", "-f", name],
            check=False,
            capture_output=True,
        )


def run_drills(report_path: Path) -> dict:
    from sqlalchemy import func, or_

    from app.core.config import settings
    from app.db.database import SessionLocal
    from app.models.chat import Conversation
    from app.models.conversation_turn import ConversationTurn
    from app.models.user import User
    from app.services.chat.turn_executor import (
        cancel_pending_turn,
        create_turn,
        fail_orphaned_turns,
    )

    cutoff = _utcnow() - timedelta(seconds=settings.TURN_STALE_SECONDS)
    with SessionLocal() as db:
        existing_stale = (
            db.query(func.count(ConversationTurn.id))
            .filter(
                or_(
                    (ConversationTurn.status == "pending")
                    & (ConversationTurn.created_at < cutoff),
                    (ConversationTurn.status == "running")
                    & (ConversationTurn.heartbeat_at < cutoff),
                )
            )
            .scalar()
        )
        if existing_stale:
            raise RuntimeError(
                "Existing stale turns found; run normal recovery before this drill"
            )
        marker = uuid.uuid4().hex[:10]
        user = User(
            username=f"resilience_drill_{marker}",
            email=f"resilience-{marker}@invalid.local",
            hashed_password="not-a-login-account",
            is_active=False,
        )
        db.add(user)
        db.flush()
        conversation = Conversation(
            id=f"resilience-{marker}",
            user_id=user.id,
            title="Resilience drill",
            type="general",
            mode="chat",
        )
        db.add(conversation)
        db.commit()
        user_id = user.id
        conversation_id = conversation.id

    try:
        turn_id, conflicts = _run_concurrency(conversation_id, user_id)
        with SessionLocal() as db:
            if not cancel_pending_turn(db, turn_id, user_id):
                raise RuntimeError("Could not clear concurrency drill turn")
            conversation = db.get(Conversation, conversation_id)
            kill_turn = create_turn(
                db,
                conversation,
                user_id=user_id,
                mode="agent",
                message="worker kill drill",
            )
            kill_turn_id = kill_turn.id

        child = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--claim", kill_turn_id],
            stdout=subprocess.PIPE,
            text=True,
        )
        claimed = child.stdout.readline().strip() if child.stdout else ""
        if claimed != "CLAIMED":
            child.kill()
            raise RuntimeError(f"Worker child failed to claim turn: {claimed}")
        child.terminate()
        child.wait(timeout=10)

        with SessionLocal() as db:
            row = db.get(ConversationTurn, kill_turn_id)
            row.heartbeat_at = _utcnow() - timedelta(
                seconds=settings.TURN_STALE_SECONDS + 1
            )
            db.commit()
        recovered_count = asyncio.run(fail_orphaned_turns())
        with SessionLocal() as db:
            recovered_status = db.get(ConversationTurn, kill_turn_id).status
        if recovered_count != 1 or recovered_status != "failed":
            raise RuntimeError("Killed worker turn was not recovered")

        network = asyncio.run(_run_network_outage())
        report = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "concurrency": {"created": 1, "conflicts": conflicts},
            "worker_kill": {
                "process_exit_code": child.returncode,
                "recovered_turns": recovered_count,
                "terminal_status": recovered_status,
            },
            "network_outage": network,
            "passed": True,
        }
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return report
    finally:
        with SessionLocal() as db:
            user = db.get(User, user_id)
            if user is not None:
                db.delete(user)
                db.commit()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claim", metavar="TURN_ID")
    parser.add_argument(
        "--report",
        default="data/release/resilience-drill.json",
    )
    args = parser.parse_args()
    if args.claim:
        return _claim_child(args.claim)
    report = run_drills(Path(args.report).resolve())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
