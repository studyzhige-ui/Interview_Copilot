"""Real authentication through async HTTP and live transport, without sockets."""

from datetime import timedelta
import threading

from fastapi import Depends, FastAPI, HTTPException
import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.security import (
    authenticate_token,
    create_access_token,
    get_current_user,
    get_password_hash,
    token_claims_for,
)
from app.core.token_blacklist import revoke
from app.db.database import Base, get_db
from app.db.types import utc_now
from app.identity.application import local_unlock, supabase_auth
from app.interviews.application import live_media
from app.models.external_identity import LocalUnlockCredential
from app.models.interview_record import InterviewRecord
from app.models.mock_media import MockMediaLease
from app.models.user import User
from app.usage import runtime
from app.usage.middleware import ConsumptionContextMiddleware
from tests.test_core.test_unified_auth import auth_config, claims, token  # noqa: F401


@pytest.fixture
def records(tmp_path, auth_config, monkeypatch):  # noqa: F811
    engine = create_engine(
        f"sqlite:///{tmp_path / 'auth.sqlite'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=True)
    payload = claims()
    with factory() as db:
        user = User(
            username="context-owner",
            email=payload["email"],
            hashed_password=get_password_hash("legacy-local-password"),
            is_active=True,
        )
        db.add(user)
        db.commit()
        user = supabase_auth.bind_profile(
            db,
            payload,
            legacy_username=user.username,
            legacy_password="legacy-local-password",
        )
        local_unlock.enroll(db, user, "separate-unlock-password")
        local_jwt = create_access_token(token_claims_for(user))
        offline_jwt = local_unlock.unlock(
            db, payload["email"], "separate-unlock-password"
        )
        record = InterviewRecord(
            user_id=user.id,
            source="mock",
            status="mock_in_progress",
            title="Synthetic live session",
        )
        db.add(record)
        db.flush()
        live_media.claim(
            db,
            record_id=record.id,
            username=user.username,
            client_session_id="fixture",
            connection_id="connection",
        )
        ids = user.id, user.username, record.id
    try:
        yield (
            factory,
            ids,
            {
                "local": local_jwt,
                "supabase": token(auth_config, payload),
                "local_unlock": offline_jwt,
            },
            payload,
        )
    finally:
        engine.dispose()


@pytest.mark.parametrize("provider", ["local", "supabase", "local_unlock"])
async def test_real_auth_binds_async_and_sync_endpoint_consumption(
    records, monkeypatch, provider
):
    factory, (uid, _, _), credentials, _ = records
    monkeypatch.setattr(
        settings, "AUTH_PROVIDER", "local" if provider == "local" else "supabase"
    )
    app = FastAPI()
    app.add_middleware(ConsumptionContextMiddleware)

    def database():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = database

    @app.get("/async")
    async def async_route(user=Depends(get_current_user)):
        return {"owner": user.id, "consumption_owner": runtime.current().user_id}

    @app.get("/sync")
    def sync_route(user=Depends(get_current_user)):
        return {"owner": user.id, "consumption_owner": runtime.current().user_id}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://fixture"
    ) as client:
        for route in ["/async", "/sync"]:
            response = await client.get(
                route, headers={"Authorization": f"Bearer {credentials[provider]}"}
            )
            assert response.status_code == 200
            assert response.json() == {"owner": uid, "consumption_owner": uid}
        assert (await client.get("/async")).status_code == 401
    assert runtime._scope.get() is None


@pytest.mark.parametrize("provider", ["local", "supabase", "local_unlock"])
async def test_live_authorize_uses_real_auth_off_thread_and_rechecks_revocation(
    records, monkeypatch, provider
):
    factory, (uid, username, rid), credentials, _ = records
    monkeypatch.setattr(
        settings, "AUTH_PROVIDER", "local" if provider == "local" else "supabase"
    )
    caller = threading.get_ident()

    def session_in_worker():
        assert threading.get_ident() != caller
        return factory()

    monkeypatch.setattr(live_media, "SessionLocal", session_in_worker)
    # ASR/model construction is unrelated; authentication and lease SQL stay real.
    monkeypatch.setattr(live_media, "LiveASR", lambda: None)
    live = live_media.LiveInterview(
        record_id=rid,
        user_id=uid,
        username=username,
        token=credentials[provider],
        connection_id="connection",
    )
    with factory() as db:
        lease = db.get(MockMediaLease, rid)
        lease.expires_at = utc_now() + timedelta(seconds=2)
        db.commit()
    await live.authorize()
    with factory() as db:
        renewed = db.get(MockMediaLease, rid).expires_at
        assert renewed > utc_now() + timedelta(seconds=20)
        if provider == "supabase":
            body = supabase_auth.verify_cloud_token(credentials[provider])
            identity = supabase_auth.token_identity(credentials[provider])
        elif provider == "local_unlock":
            body = local_unlock.decode_local_token(credentials[provider])
            identity = body["jti"]
        else:
            from app.core.security import decode_token

            body = decode_token(credentials[provider])
            identity = body["jti"]
        revoke(db, identity, exp=body["exp"])
        db.commit()
    with pytest.raises(HTTPException) as caught:
        await live.authorize()
    assert caught.value.status_code == 401
    with factory() as db:
        assert db.get(MockMediaLease, rid).expires_at == renewed


def test_unlock_cannot_adopt_a_generation_rotated_after_password_check(
    records, monkeypatch
):
    factory, (uid, _, _), _, payload = records
    with factory() as db:
        original_commit = db.commit

        def rotate_after_commit():
            original_commit()
            with factory() as concurrent:
                local_unlock.enroll(
                    concurrent, concurrent.get(User, uid), "rotated-local-password"
                )

        monkeypatch.setattr(db, "commit", rotate_after_commit)
        issued = local_unlock.unlock(db, payload["email"], "separate-unlock-password")
    assert local_unlock.decode_local_token(issued)["credential_version"] == 1
    with factory() as db:
        assert db.get(LocalUnlockCredential, uid).credential_version == 2
        with pytest.raises(HTTPException):
            authenticate_token(issued, db)
