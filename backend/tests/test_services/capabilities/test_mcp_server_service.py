from app.models.user import User
from app.services.capabilities import mcp_server_service


def _user(db_session):
    row = User(username="mcp-user", hashed_password="x")
    db_session.add(row)
    db_session.commit()
    return row


def test_mcp_config_crud_encrypts_secrets(db_session):
    user = _user(db_session)
    created = mcp_server_service.create_server(
        db_session,
        user.id,
        {
            "name": "demo",
            "transport": "streamable_http",
            "url": "https://example.com/mcp",
            "args": [],
            "headers": {"Authorization": "Bearer secret"},
            "env": {},
            "enabled": True,
        },
    )
    assert created["has_secrets"] is True

    row = mcp_server_service.get_server(db_session, user.id, created["id"])
    assert "Bearer secret" not in row.secrets_ciphertext
    config = mcp_server_service.config_for(row)
    assert config.headers == {"Authorization": "Bearer secret"}

    updated = mcp_server_service.update_server(
        db_session,
        user.id,
        row.id,
        {
            "name": "demo-renamed",
            "transport": "streamable_http",
            "url": "https://example.com/new-mcp",
            "args": [],
            "headers": None,
            "env": None,
            "enabled": False,
        },
    )
    assert updated["name"] == "demo-renamed"
    assert (
        mcp_server_service.config_for(row).headers["Authorization"] == "Bearer secret"
    )
    assert mcp_server_service.delete_server(db_session, user.id, row.id) is True
