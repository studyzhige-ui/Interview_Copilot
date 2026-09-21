"""Guard unit tests use explicit SQL-result doubles; real SQL is tested in test_db."""

from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest
from sqlalchemy import create_engine
from app.rag import hybrid_index as index
from app.rag.index.identity import current_index_identity


def _session(monkeypatch, *, extension="0.8.6", generation=None):
    db = MagicMock()
    db.bind.dialect.name = "postgresql"
    db.__enter__.return_value = db
    db.execute.return_value.scalar.return_value = extension
    db.get.return_value = generation
    monkeypatch.setattr("app.db.database.SessionLocal", lambda: db)
    return db


def test_missing_extension_is_not_a_successful_startup(monkeypatch):
    _session(monkeypatch, extension=None)
    with pytest.raises(index.RetrievalIndexUnavailable, match="extension"):
        index.validate_index_storage()


def test_unreachable_storage_does_not_degrade_to_success(monkeypatch):
    db = _session(monkeypatch)
    db.execute.side_effect = ConnectionError("database down")
    with pytest.raises(ConnectionError):
        index.validate_index_storage()


def test_new_generation_can_be_absent_without_ddl(monkeypatch):
    db = _session(monkeypatch)
    index.validate_index_storage()
    assert not db.commit.called
    assert all("CREATE " not in str(c.args[0]) for c in db.execute.call_args_list)


def test_identity_and_dimension_must_both_match(monkeypatch):
    identity = current_index_identity()
    for dim, payload in [
        (identity.embedding_dim + 1, identity.to_dict()),
        (identity.embedding_dim, {"wrong": "model"}),
    ]:
        _session(
            monkeypatch,
            generation=SimpleNamespace(embedding_dim=dim, identity_json=payload),
        )
        with pytest.raises(index.RetrievalIndexUnavailable, match="identity"):
            index.validate_index_storage()


def test_matching_identity_is_valid(monkeypatch):
    identity = current_index_identity()
    _session(
        monkeypatch,
        generation=SimpleNamespace(
            embedding_dim=identity.embedding_dim, identity_json=identity.to_dict()
        ),
    )
    index.validate_index_storage()


def test_sqlite_is_not_silently_a_vector_backend(monkeypatch):
    with create_engine("sqlite://").connect() as connection:
        with pytest.raises(index.RetrievalIndexUnavailable):
            index._limits(SimpleNamespace(bind=connection.engine))


@pytest.mark.parametrize(
    "filters",
    [
        {"arbitrary": "x"},
        {"document_id": [None]},
        {"source_kind": ["x"]},
        {"document_id": ["x"] * 1001},
    ],
)
def test_invalid_scope_rejected_before_query(filters):
    with pytest.raises(ValueError):
        index._scope(1, filters)


@pytest.mark.parametrize("owner", [None, True, 0, -1, "1"])
def test_trusted_user_key_must_be_a_real_positive_integer(owner):
    with pytest.raises(ValueError):
        index._scope(owner, None)
