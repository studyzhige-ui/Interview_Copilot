from types import SimpleNamespace

from app.core.rate_limit import user_or_ip_key
from app.core.security import create_access_token


def _request(*, authorization: str = "", host: str = "127.0.0.1"):
    return SimpleNamespace(
        headers={"authorization": authorization},
        client=SimpleNamespace(host=host),
    )


def test_authenticated_quota_uses_stable_subject():
    token = create_access_token({"sub": "42", "token_version": 0})

    assert user_or_ip_key(_request(authorization=f"Bearer {token}")) == "user:42"


def test_invalid_or_missing_token_quota_falls_back_to_ip():
    assert user_or_ip_key(_request(host="10.0.0.8")) == "ip:10.0.0.8"
    assert (
        user_or_ip_key(_request(authorization="Bearer broken", host="10.0.0.9"))
        == "ip:10.0.0.9"
    )
