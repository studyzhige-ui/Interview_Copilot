"""Exercise real ASGI authentication and independently created SQL sessions."""

from io import BytesIO

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.api import auth, file_assets, unified_auth
from app.api.interviews import mock, records
from app.core import storage
from app.core.security import create_access_token, get_current_user, token_claims_for
from app.db import database
from app.files.application.file_asset_service import store_validated_file_asset
from app.models.user import User


@pytest.fixture(params=["local", "supabase-local-unlock"])
def real_auth_app(tmp_path, monkeypatch, request):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'auth.db'}", connect_args={"check_same_thread": False}
    )
    database.Base.metadata.create_all(engine)
    opened = []

    class ObservedSession(Session):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.was_closed = False
            opened.append(self)

        def close(self):
            super().close()
            self.was_closed = True

    factory = sessionmaker(bind=engine, class_=ObservedSession)
    monkeypatch.setattr(database, "SessionLocal", factory)
    mode = request.param
    monkeypatch.setattr(
        storage.settings, "AUTH_PROVIDER", "local" if mode == "local" else "supabase"
    )
    monkeypatch.setattr(
        storage.settings, "SUPABASE_URL", "https://session-fixture.supabase.invalid"
    )
    monkeypatch.setattr(storage.settings, "STORAGE_DIR", str(tmp_path / "objects"))
    monkeypatch.setattr(storage.settings, "STORAGE_BACKEND", "filesystem")
    monkeypatch.setattr(storage.settings, "STORAGE_MIN_FREE_BYTES", 0)
    with factory() as db:
        owner = User(username="real-auth-owner", hashed_password="synthetic")
        db.add(owner)
        db.commit()
        token = create_access_token(token_claims_for(owner))
        asset = store_validated_file_asset(
            db,
            user_id=owner.username,
            filename="avatar.png",
            purpose="avatar",
            file_obj=BytesIO(b"\x89PNG\r\n\x1a\nsynthetic"),
            content_type="image/png",
            size_bytes=17,
        )
        asset_id = asset.id
        if mode == "supabase-local-unlock":
            from app.models.external_identity import ExternalIdentity
            from app.identity.application import local_unlock, supabase_auth

            db.add(
                ExternalIdentity(
                    user_id=owner.id,
                    issuer=supabase_auth.issuer(),
                    subject="00000000-0000-0000-0000-000000000001",
                    email="scope@example.com",
                )
            )
            db.commit()
            local_unlock.enroll(db, owner, "synthetic-local-password")
    opened.clear()
    app = FastAPI()
    app.include_router(auth.router, prefix="/api/v1/auth")
    app.include_router(file_assets.router, prefix="/api/v1")
    app.include_router(unified_auth.router, prefix="/api/v1/auth")
    app.include_router(records.router, prefix="/api/v1")
    app.include_router(mock.router, prefix="/api/v1")

    @app.get("/scope-attribution")
    async def attribution(
        user: User = Depends(get_current_user),
        db: Session = Depends(database.get_db, scope="function"),
    ):
        from sqlalchemy.orm import object_session
        from app.usage.runtime import current

        assert object_session(user) is db
        return {"owner": user.id, "attribution": current().user_id}

    # No override of either get_current_user or get_db: use the actual dependency graph.
    with TestClient(app) as client:
        if mode == "supabase-local-unlock":
            response = client.post(
                "/api/v1/auth/local-unlock",
                json={
                    "email": "scope@example.com",
                    "password": "synthetic-local-password",
                },
            )
            assert response.status_code == 200, response.text
            token = response.json()["access_token"]
        opened.clear()
        yield client, factory, token, asset_id, opened
    engine.dispose()


def test_avatar_and_profile_share_real_auth_session(real_auth_app):
    client, factory, token, asset_id, opened = real_auth_app
    headers = {"Authorization": f"Bearer {token}"}
    response = client.post(
        "/api/v1/auth/me/avatar", headers=headers, json={"file_asset_id": asset_id}
    )
    assert response.status_code == 200, response.text
    assert len(opened) == 1
    assert all(
        session.was_closed and not session.in_transaction() for session in opened
    )
    opened.clear()
    response = client.patch(
        "/api/v1/auth/me", headers=headers, json={"nickname": "Updated"}
    )
    assert response.status_code == 200, response.text
    assert len(opened) == 1
    assert all(
        session.was_closed and not session.in_transaction() for session in opened
    )
    with factory() as db:
        user = db.query(User).filter_by(username="real-auth-owner").one()
        assert user.nickname == "Updated" and user.avatar_url.startswith("local://")


def test_download_closes_shared_auth_session_before_storage_body(
    real_auth_app, monkeypatch
):
    from contextlib import contextmanager

    client, _, token, asset_id, opened = real_auth_app
    original = storage.open_object
    seen = []

    @contextmanager
    def observed(*args, **kwargs):
        assert len(opened) == 1
        assert all(
            session.was_closed and not session.in_transaction() for session in opened
        )
        seen.append(True)
        with original(*args, **kwargs) as source:
            yield source

    monkeypatch.setattr(storage, "open_object", observed)
    response = client.get(
        f"/api/v1/file-assets/{asset_id}/download",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.content == b"\x89PNG\r\n\x1a\nsynthetic"
    assert seen == [True]


def test_real_auth_revocation_and_disabled_owner_still_enforced(real_auth_app):
    client, factory, token, _, opened = real_auth_app
    headers = {"Authorization": f"Bearer {token}"}
    with factory() as db:
        owner = db.query(User).filter_by(username="real-auth-owner").one()
        owner.token_version += 1
        db.commit()
    opened.clear()
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
    assert len(opened) == 1 and opened[0].was_closed and not opened[0].in_transaction()
    with factory() as db:
        owner = db.query(User).filter_by(username="real-auth-owner").one()
        owner.token_version -= 1
        owner.is_active = False
        db.commit()
    opened.clear()
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
    assert len(opened) == 1 and opened[0].was_closed and not opened[0].in_transaction()


def test_async_attribution_remains_bound_in_request_context(real_auth_app):
    client, _, token, _, opened = real_auth_app
    response = client.get(
        "/scope-attribution", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert response.json()["owner"] == response.json()["attribution"]
    assert len(opened) == 1 and opened[0].was_closed and not opened[0].in_transaction()


def test_interview_sse_polls_after_auth_session_closes(real_auth_app, monkeypatch):
    from app.interviews.application import record_admin
    from app.models.interview_record import InterviewRecord

    client, factory, token, _, opened = real_auth_app
    monkeypatch.setattr(record_admin, "SessionLocal", factory)
    with factory() as db:
        owner = db.query(User).filter_by(username="real-auth-owner").one()
        db.add(
            InterviewRecord(
                id="ir_scope",
                user_id=owner.id,
                source="upload",
                status="completed",
                title="Scope",
            )
        )
        db.commit()
    original = record_admin.poll_record_snapshot
    seen = []

    def poll(record_id):
        assert opened and all(
            session.was_closed and not session.in_transaction() for session in opened
        )
        result = original(record_id)
        assert all(
            session.was_closed and not session.in_transaction() for session in opened
        )
        seen.append(True)
        return result

    monkeypatch.setattr(record_admin, "poll_record_snapshot", poll)
    opened.clear()
    response = client.get(
        "/api/v1/interview-records/ir_scope/events",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert '"type": "done"' in response.text
    assert seen == [True]
    assert len(opened) == 3 and all(
        session.was_closed and not session.in_transaction() for session in opened
    )


def test_real_persisted_jti_revocation_prevents_profile_mutation(real_auth_app):
    import jwt
    from app.core.token_blacklist import revoke

    client, factory, token, _, opened = real_auth_app
    claims = jwt.decode(token, options={"verify_signature": False})
    with factory() as db:
        revoke(db, claims["jti"], claims["exp"])
        db.commit()
    opened.clear()
    response = client.patch(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"nickname": "Must not persist"},
    )
    assert response.status_code == 401
    assert len(opened) == 1 and opened[0].was_closed and not opened[0].in_transaction()
    with factory() as db:
        assert (
            db.query(User).filter_by(username="real-auth-owner").one().nickname is None
        )


def test_tts_closes_shared_auth_session_before_long_work(real_auth_app, monkeypatch):
    from types import SimpleNamespace
    from app.media.application.tts_service import tts_service

    client, _, token, _, opened = real_auth_app
    seen = []

    async def synthesize(**kwargs):
        assert (
            len(opened) == 1 and opened[0].was_closed and not opened[0].in_transaction()
        )
        seen.append(True)
        return SimpleNamespace(data=b"synthetic audio", media_type="audio/wav")

    monkeypatch.setattr(tts_service, "synthesize", synthesize)
    response = client.post(
        "/api/v1/mock-interviews/tts",
        headers={"Authorization": f"Bearer {token}"},
        json={"text": "Synthetic test"},
    )
    assert response.status_code == 200 and response.content == b"synthetic audio"
    assert seen == [True]
