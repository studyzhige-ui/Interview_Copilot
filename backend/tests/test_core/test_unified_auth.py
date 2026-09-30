"""Synthetic identity, ownership and local-capability tests; no live accounts."""

from datetime import timedelta
from types import SimpleNamespace
import time
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException

from app.core.config import settings
from app.core.security import authenticate_token, get_password_hash
from app.core.token_blacklist import revoke
from app.db.types import utc_now
from app.identity.application import supabase_auth as cloud, local_unlock
from app.models.external_identity import ExternalIdentity, LocalUnlockCredential
from app.models.user import User


@pytest.fixture
def auth_config(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_PROVIDER", "supabase")
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://fixture.supabase.co")
    monkeypatch.setattr(settings, "SUPABASE_PUBLISHABLE_KEY", "sb_publishable_fixture")
    monkeypatch.setattr(settings, "SECRET_KEY", "synthetic-local-key-" + "x" * 48)
    key = ec.generate_private_key(ec.SECP256R1())
    monkeypatch.setattr(
        cloud,
        "_jwks_client",
        lambda _: SimpleNamespace(
            get_signing_key_from_jwt=lambda _: SimpleNamespace(key=key.public_key())
        ),
    )
    return key


def claims(**changes):
    now = int(time.time())
    return {
        "iss": cloud.issuer(),
        "aud": "authenticated",
        "sub": str(uuid4()),
        "exp": now + 3600,
        "iat": now,
        "session_id": str(uuid4()),
        "role": "authenticated",
        "email": "owner@example.test",
        "is_anonymous": False,
        "amr": [{"method": "password", "timestamp": now}],
        **changes,
    }


def token(key, payload):
    return jwt.encode(payload, key, algorithm="ES256", headers={"kid": "fixture-key"})


def bind(db, payload):
    return cloud.bind_profile(db, payload)


def test_cloud_validation_accepts_only_verified_project_user(auth_config):
    payload = claims(user_metadata={"role": "service_role", "local_owner_id": 999})
    assert (
        cloud.verify_cloud_token(token(auth_config, payload))["sub"] == payload["sub"]
    )


@pytest.mark.parametrize(
    "change",
    [
        {"iss": "https://attacker.example/auth/v1"},
        {"aud": "anon"},
        {"exp": 1},
        {"iat": int(time.time()) + 86400},
        {"sub": "1"},
        {"session_id": "not-a-session"},
        {"session_id": None},
        {"session_id": True},
        {"role": "service_role"},
        {"is_anonymous": True},
        {"exp": None},
    ],
)
def test_cloud_validation_rejects_invalid_claims(auth_config, change):
    with pytest.raises(HTTPException) as caught:
        cloud.verify_cloud_token(token(auth_config, claims(**change)))
    assert caught.value.status_code == 401


def test_wrong_signature_missing_exp_and_unsigned_tokens_are_rejected(auth_config):
    forged = token(ec.generate_private_key(ec.SECP256R1()), claims())
    missing = claims()
    del missing["exp"]
    for value in [
        forged,
        token(auth_config, missing),
        jwt.encode(claims(), "", algorithm="none"),
    ]:
        with pytest.raises(HTTPException) as caught:
            cloud.verify_cloud_token(value)
        assert caught.value.status_code == 401


def test_jwks_outage_is_unavailable_not_false_logout(auth_config, monkeypatch):
    def unavailable(_):
        raise jwt.PyJWKClientConnectionError("offline")

    monkeypatch.setattr(cloud, "_jwks_client", unavailable)
    with pytest.raises(HTTPException) as caught:
        cloud.verify_cloud_token(token(auth_config, claims()))
    assert caught.value.status_code == 503


def test_legacy_hs256_is_verified_remotely_without_shared_secret(
    auth_config, monkeypatch
):
    payload = claims()
    value = jwt.encode(payload, "synthetic-cloud-signing-key" * 3, algorithm="HS256")
    calls = []
    monkeypatch.setattr(
        cloud,
        "online_user",
        lambda t: (
            calls.append(t)
            or {
                "id": payload["sub"],
                "email": payload["email"],
                "email_confirmed_at": "fixture",
            }
        ),
    )
    assert cloud.verify_cloud_token(value)["sub"] == payload["sub"]
    assert calls == [value]


def test_identity_binding_is_stable_and_never_uses_email_as_proof(
    auth_config, db_session
):
    old = User(
        username="legacy",
        email="owner@example.test",
        hashed_password=get_password_hash("old-local-password"),
        is_active=True,
    )
    db_session.add(old)
    db_session.commit()
    original_id = old.id
    payload = claims()
    with pytest.raises(HTTPException) as conflict:
        bind(db_session, payload)
    assert conflict.value.status_code == 409
    with pytest.raises(HTTPException):
        cloud.bind_profile(
            db_session, payload, legacy_username="legacy", legacy_password="wrong"
        )
    result = cloud.bind_profile(
        db_session,
        payload,
        legacy_username="legacy",
        legacy_password="old-local-password",
    )
    assert result.id == original_id
    assert result.token_version == 1
    assert bind(db_session, payload).id == original_id
    assert db_session.query(User).count() == 1
    assert db_session.get(ExternalIdentity, original_id).subject == payload["sub"]


def test_new_cloud_id_cannot_rebind_existing_owner(auth_config, db_session):
    payload = claims()
    user = bind(db_session, payload)
    user.hashed_password = get_password_hash("local-proof-password")
    db_session.commit()
    with pytest.raises(HTTPException) as caught:
        cloud.bind_profile(
            db_session,
            claims(email="another@example.test"),
            legacy_username=user.username,
            legacy_password="local-proof-password",
        )
    assert caught.value.status_code == 409
    assert db_session.get(ExternalIdentity, user.id).subject == payload["sub"]


def test_cloud_owner_gate_checks_disabled_and_local_revocation(auth_config, db_session):
    payload = claims()
    user = bind(db_session, payload)
    value = token(auth_config, payload)
    assert authenticate_token(value, db_session).id == user.id
    user.is_active = False
    db_session.commit()
    with pytest.raises(HTTPException):
        authenticate_token(value, db_session)
    user.is_active = True
    db_session.commit()
    revoke(db_session, cloud.token_identity(value), exp=payload["exp"])
    db_session.commit()
    with pytest.raises(HTTPException):
        authenticate_token(value, db_session)


def test_independent_unlock_works_offline_without_cloud_privileges(
    auth_config, db_session, monkeypatch
):
    payload = claims()
    user = bind(db_session, payload)
    local_unlock.enroll(db_session, user, "separate-local-password")

    def no_network(*args, **kwargs):
        pytest.fail("local unlock must not contact cloud Auth")

    monkeypatch.setattr(cloud, "online_user", no_network)
    monkeypatch.setattr(cloud, "_jwks_client", no_network)
    value = local_unlock.unlock(db_session, payload["email"], "separate-local-password")
    assert authenticate_token(value, db_session).id == user.id
    with pytest.raises(HTTPException) as caught:
        cloud.verify_cloud_token(value, online=True)
    assert caught.value.status_code == 401
    assert local_unlock.decode_local_token(value)["scope"] == "local_business"


def test_unlock_rotation_revocation_and_disabled_owner_are_enforced(
    auth_config, db_session
):
    payload = claims()
    user = bind(db_session, payload)
    local_unlock.enroll(db_session, user, "separate-local-password")
    first = local_unlock.unlock(db_session, payload["email"], "separate-local-password")
    local_unlock.enroll(db_session, user, "rotated-local-password")
    with pytest.raises(HTTPException):
        authenticate_token(first, db_session)
    current = local_unlock.unlock(
        db_session, payload["email"], "rotated-local-password"
    )
    body = local_unlock.decode_local_token(current)
    revoke(db_session, body["jti"], exp=body["exp"])
    db_session.commit()
    with pytest.raises(HTTPException):
        authenticate_token(current, db_session)
    user.is_active = False
    db_session.commit()
    with pytest.raises(HTTPException):
        local_unlock.unlock(db_session, payload["email"], "rotated-local-password")


def test_unlock_lockout_persists_and_expired_sessions_are_rejected(
    auth_config, db_session
):
    payload = claims()
    user = bind(db_session, payload)
    local_unlock.enroll(db_session, user, "separate-local-password")
    valid = local_unlock.unlock(db_session, payload["email"], "separate-local-password")
    decoded = local_unlock.decode_local_token(valid)
    decoded["exp"] = 1
    expired = jwt.encode(decoded, settings.SECRET_KEY, algorithm="HS256")
    with pytest.raises(HTTPException):
        authenticate_token(expired, db_session)
    for _ in range(5):
        with pytest.raises(HTTPException):
            local_unlock.unlock(db_session, payload["email"], "wrong")
    with pytest.raises(HTTPException) as caught:
        local_unlock.unlock(db_session, payload["email"], "separate-local-password")
    assert caught.value.status_code == 429
    row = db_session.get(LocalUnlockCredential, user.id)
    row.locked_until = utc_now() - timedelta(seconds=1)
    db_session.commit()
    assert local_unlock.unlock(db_session, payload["email"], "separate-local-password")


def test_account_link_requires_recent_cloud_password_proof(auth_config):
    from app.api.unified_auth import require_recent_password

    require_recent_password(claims())
    for payload in [
        claims(amr=[]),
        claims(amr=[{"method": "token_refresh", "timestamp": int(time.time())}]),
        claims(amr=[{"method": "password", "timestamp": 1}]),
    ]:
        with pytest.raises(HTTPException):
            require_recent_password(payload)
