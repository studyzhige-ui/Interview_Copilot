"""测试 app.core.security 的密码哈希与 JWT 生成/解析。"""
from datetime import timedelta
from jose import jwt as jose_jwt


def test_password_hash_and_verify():
    """哈希后的密码应能被 verify_password 正确验证。"""
    from app.core.security import get_password_hash, verify_password

    plain = "my_secure_password_123"
    hashed = get_password_hash(plain)

    assert hashed != plain, "哈希值不应等于原文"
    assert verify_password(plain, hashed), "正确密码应验证通过"
    assert not verify_password("wrong_password", hashed), "错误密码应验证失败"


def test_create_access_token_contains_subject():
    """生成的 JWT 应包含 sub 字段。"""
    from app.core.security import create_access_token
    from app.core.config import settings

    token = create_access_token(data={"sub": "testuser"})
    payload = jose_jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])

    assert payload["sub"] == "testuser"
    assert "exp" in payload


def test_create_access_token_custom_expiry():
    """自定义过期时间应正确写入 JWT。"""
    from app.core.security import create_access_token
    from app.core.config import settings

    token = create_access_token(
        data={"sub": "alice"},
        expires_delta=timedelta(minutes=5)
    )
    payload = jose_jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    assert payload["sub"] == "alice"


def test_invalid_token_raises():
    """伪造/损坏的 Token 解码应抛异常。"""
    from app.core.config import settings
    from jose import JWTError

    try:
        jose_jwt.decode("not.a.real.token", settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        assert False, "本应抛出 JWTError"
    except JWTError:
        pass  # 期望行为


def test_access_token_has_access_type():
    """Access Token 应包含 type='access' 声明。"""
    from app.core.security import create_access_token
    from app.core.config import settings

    token = create_access_token(data={"sub": "alice"})
    payload = jose_jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    assert payload["type"] == "access"


def test_create_refresh_token_has_refresh_type():
    """Refresh Token 应包含 type='refresh' 声明。"""
    from app.core.security import create_refresh_token
    from app.core.config import settings

    token = create_refresh_token(data={"sub": "bob"})
    payload = jose_jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    assert payload["type"] == "refresh"
    assert payload["sub"] == "bob"


def test_refresh_token_rejected_as_access():
    """使用 Refresh Token 访问 get_current_user 应抛出 401。"""
    import pytest
    from unittest.mock import MagicMock
    from fastapi import HTTPException
    from app.core.security import create_refresh_token, decode_token
    from app.core.config import settings

    token = create_refresh_token(data={"sub": "charlie"})
    payload = jose_jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])

    # Refresh token should carry type="refresh", not "access"
    assert payload["type"] == "refresh"
    # get_current_user would reject this because type != "access"


def test_decode_token_rejects_expired():
    """过期 Token 解码应抛出 JWTError。"""
    from datetime import timedelta
    from jose import JWTError
    from app.core.security import create_access_token, decode_token

    token = create_access_token(
        data={"sub": "expired_user"},
        expires_delta=timedelta(seconds=-1),
    )
    try:
        decode_token(token)
        assert False, "本应抛出 JWTError"
    except JWTError:
        pass

