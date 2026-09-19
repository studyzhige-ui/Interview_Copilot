"""No outbound destination/credential failover on unavailable account state."""

from types import SimpleNamespace

import pytest

from app.core.model_connection_error import ModelConnectionUnavailable
from app.core import llm_client_factory, model_readiness, user_model_selection
from app.core.error_messages import humanize_error
from app.models.user import User
from app.models.user_model_credentials import UserModelCredential
from app.services.auth import user_api_key_service as keys
from app.core.secrets import encrypt_secret


def profile():
    return SimpleNamespace(
        id="test/model",
        provider="test",
        api_base="https://default.example/v1",
        api_key_env="TEST_PROVIDER_KEY",
    )


def test_provider_lookup_error_cannot_construct_native_client(monkeypatch, caplog):
    monkeypatch.setattr("app.core.config.settings.APP_EDITION", "community")
    monkeypatch.setattr(llm_client_factory, "resolve_api_key", lambda *_a, **_k: "key")

    def broken():
        raise RuntimeError("private-connection-detail")

    monkeypatch.setattr("app.db.database.SessionLocal", broken)

    def forbidden(**_kwargs):
        pytest.fail("must not create a fallback client")

    monkeypatch.setattr(llm_client_factory, "AsyncOpenAI", forbidden)
    with pytest.raises(ModelConnectionUnavailable) as raised:
        llm_client_factory.get_async_openai_client(profile(), user_id="alice")
    assert "private-connection-detail" not in humanize_error(raised.value)
    assert "private-connection-detail" not in caplog.text


def test_missing_key_can_use_deployment_but_lookup_failure_cannot(monkeypatch):
    monkeypatch.setenv("TEST_PROVIDER_KEY", "deployment-key")
    monkeypatch.setattr(keys, "get_user_api_key_plaintext", lambda *_a, **_k: None)
    assert model_readiness.resolve_api_key(profile(), "alice") == "deployment-key"

    def broken(*_a, **_k):
        raise ConnectionError("private-detail")

    monkeypatch.setattr(keys, "get_user_api_key_plaintext", broken)
    with pytest.raises(ModelConnectionUnavailable):
        model_readiness.resolve_api_key(profile(), "alice")
    assert model_readiness.resolve_api_key(profile()) == "deployment-key"


def test_selection_read_error_is_not_absent_user_selection(monkeypatch):
    def broken():
        raise ConnectionError("unavailable")

    monkeypatch.setattr("app.db.database.SessionLocal", broken)
    with pytest.raises(ModelConnectionUnavailable):
        user_model_selection._load_user_selection("alice")


def test_cached_secret_does_not_bypass_cross_process_rotation_or_delete(db_session):
    keys._decrypt_cache.clear()
    try:
        db_session.add(User(username="authority-test", hashed_password="x"))
        db_session.commit()
        keys.set_user_api_key(
            "authority-test", "test", "old-private-key", db=db_session
        )
        assert (
            keys.get_user_api_key_plaintext("authority-test", "test", db=db_session)
            == "old-private-key"
        )
        # Deliberately bypass the service's in-process invalidation, as another
        # worker/operator would. The next dispatch must read canonical storage.
        db_session.query(UserModelCredential).update(
            {"key_ciphertext": encrypt_secret("new-private-key")},
            synchronize_session=False,
        )
        db_session.commit()
        assert (
            keys.get_user_api_key_plaintext("authority-test", "test", db=db_session)
            == "new-private-key"
        )
        db_session.query(UserModelCredential).delete(synchronize_session=False)
        db_session.commit()
        assert (
            keys.get_user_api_key_plaintext("authority-test", "test", db=db_session)
            is None
        )
    finally:
        keys._decrypt_cache.clear()


def test_corrupt_stored_secret_is_not_absent_and_never_falls_back(
    db_session, monkeypatch
):
    from tests.conftest import patch_session_locals

    keys._decrypt_cache.clear()
    db_session.add(User(username="corrupt-key-test", hashed_password="x"))
    db_session.commit()
    keys.set_user_api_key(
        "corrupt-key-test", "test", "valid-before-corruption", db=db_session
    )
    db_session.query(UserModelCredential).update(
        {"key_ciphertext": "corrupted-ciphertext"}, synchronize_session=False
    )
    db_session.commit()
    patch_session_locals(monkeypatch, db_session, keys)
    monkeypatch.setenv("TEST_PROVIDER_KEY", "must-not-fall-back")
    try:
        with pytest.raises(ModelConnectionUnavailable):
            model_readiness.resolve_api_key(profile(), "corrupt-key-test")
    finally:
        keys._decrypt_cache.clear()
