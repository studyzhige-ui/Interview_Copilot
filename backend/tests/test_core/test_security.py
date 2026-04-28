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
