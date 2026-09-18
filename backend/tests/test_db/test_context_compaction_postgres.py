"""A real concurrent compaction publication has exactly one winner."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from alembic import command
from app.models.chat import Conversation, ConversationMessage
from app.models.user import User
from app.conversation import context_store as history
from tests.test_db.test_alembic_migrations import fresh_pg_db, _make_alembic_config  # noqa: F401


def test_concurrent_compactions_do_not_overwrite_each_other(fresh_pg_db, monkeypatch):  # noqa: F811
    command.upgrade(_make_alembic_config(fresh_pg_db), "head")
    engine = create_engine(fresh_pg_db)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(history, "SessionLocal", factory)
    try:
        with factory() as db:
            user = User(username="context-race", hashed_password="x")
            db.add(user)
            db.flush()
            db.add(
                Conversation(
                    id="race", user_id=user.id, summary="old", compaction_cursor=0
                )
            )
            db.flush()
            db.add_all(
                [
                    ConversationMessage(
                        conversation_id="race",
                        seq=i,
                        role="User" if i % 2 else "Agent",
                        content="original",
                    )
                    for i in range(1, 5)
                ]
            )
            db.commit()
        barrier = Barrier(2)

        def publish(cursor):
            barrier.wait(timeout=10)
            return bool(
                history.save(
                    "race",
                    expected_version=0,
                    through_seq=cursor,
                    state={
                        "messages": [{"role": "user", "content": f"summary-{cursor}"}]
                    },
                )
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(publish, cursor) for cursor in (2, 4)]
            assert sorted(f.result(timeout=15) for f in futures) == [False, True]
        checkpoint = history.load("race")
        assert (
            checkpoint["state"]["messages"][0]["content"]
            == f"summary-{checkpoint['through_seq']}"
        )
        with factory() as db:
            assert (
                db.query(ConversationMessage).filter_by(conversation_id="race").count()
                == 4
            )
    finally:
        engine.dispose()
