"""``app.services.memory._db_helpers`` — session_scope contract."""


def test_session_scope_does_not_close_passed_session():
    """The ``session_scope`` helper's load-bearing contract:
       * db is None → open + close (auto-manage)
       * db is not None → yield, leave OPEN (caller-managed)

    Without this contract the P1-F shared-session plumbing breaks:
    the second ``.load(..., db=db)`` would hit a closed session and
    raise ``InvalidRequestError``. Indirect coverage via
    ``test_load_universal_opens_exactly_one_db_session`` only sees
    the 1-vs-4 count; this test pins the close-vs-stay-open behavior.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.services.memory._db_helpers import session_scope

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Session = sessionmaker(bind=engine)

    # Branch 1: passing a session → helper must NOT close it.
    own = Session()
    try:
        with session_scope(own) as got:
            assert got is own
            assert own.is_active
        assert own.is_active, (
            "session_scope closed a passed-in session — breaks the "
            "P1-F shared-session contract that orchestrators rely on"
        )
    finally:
        own.close()
        engine.dispose()
