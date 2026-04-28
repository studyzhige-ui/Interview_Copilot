"""测试 auth API 的注册与登录业务逻辑。

直接调用路由 handler 函数，注入测试 db_session，不启动 FastAPI TestClient。
"""
import pytest
from unittest.mock import MagicMock
from fastapi import HTTPException


def _make_user_create(username="authuser", password="pass123", email="a@b.com"):
    """构造 UserCreate Pydantic 对象。"""
    from app.api.auth import UserCreate
    return UserCreate(username=username, password=password, email=email)


def test_register_user_success(db_session):
    """正常注册应返回 user_id。"""
    from app.api.auth import register_user

    result = register_user(_make_user_create(), db=db_session)

    assert result["message"] == "User registered successfully"
    assert "user_id" in result


def test_register_duplicate_user_raises(db_session):
    """重复注册同一 username 应抛出 400 HTTPException。"""
    from app.api.auth import register_user

    register_user(_make_user_create(username="dup"), db=db_session)

    with pytest.raises(HTTPException) as exc_info:
        register_user(_make_user_create(username="dup"), db=db_session)

    assert exc_info.value.status_code == 400
    assert "already exists" in exc_info.value.detail


def test_login_success(db_session):
    """注册后使用正确密码登录应返回 access_token。"""
    from app.api.auth import register_user, login_access_token
    from fastapi.security import OAuth2PasswordRequestForm

    register_user(_make_user_create(username="loginuser", password="correctpw"), db=db_session)

    # 模拟 OAuth2PasswordRequestForm
    form = MagicMock(spec=OAuth2PasswordRequestForm)
    form.username = "loginuser"
    form.password = "correctpw"

    result = login_access_token(db=db_session, form_data=form)

    assert "access_token" in result
    assert result["token_type"] == "bearer"


def test_login_wrong_password(db_session):
    """错误密码登录应抛出 400。"""
    from app.api.auth import register_user, login_access_token
    from fastapi.security import OAuth2PasswordRequestForm

    register_user(_make_user_create(username="wrongpw", password="correct"), db=db_session)

    form = MagicMock(spec=OAuth2PasswordRequestForm)
    form.username = "wrongpw"
    form.password = "incorrect"

    with pytest.raises(HTTPException) as exc_info:
        login_access_token(db=db_session, form_data=form)

    assert exc_info.value.status_code == 400


def test_login_nonexistent_user(db_session):
    """不存在的用户登录应抛出 400。"""
    from app.api.auth import login_access_token
    from fastapi.security import OAuth2PasswordRequestForm

    form = MagicMock(spec=OAuth2PasswordRequestForm)
    form.username = "ghost_user"
    form.password = "any"

    with pytest.raises(HTTPException) as exc_info:
        login_access_token(db=db_session, form_data=form)

    assert exc_info.value.status_code == 400
