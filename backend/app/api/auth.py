from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from jose import JWTError
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
    get_password_hash,
    verify_password,
)
from app.db.database import get_db
from app.models.user import User
from app.services.verification_code_service import CodeError, request_code, verify_code

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────


class UserCreate(BaseModel):
    username: str
    password: str
    email: EmailStr
    code: str = Field(..., description="6-digit email verification code")


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str


class RefreshRequest(BaseModel):
    refresh_token: str


class EmailRequest(BaseModel):
    email: EmailStr
    purpose: str = "register"  # "register" | "reset_password" | "change_email"


class MeUpdate(BaseModel):
    nickname: Optional[str] = Field(default=None, max_length=64)
    avatar_url: Optional[str] = Field(default=None, max_length=512)
    bio: Optional[str] = Field(default=None, max_length=2000)


class MeResponse(BaseModel):
    username: str
    email: Optional[str]
    nickname: Optional[str]
    avatar_url: Optional[str]
    bio: Optional[str]
    email_verified: bool
    created_at: str
    updated_at: str


# ── Endpoints ────────────────────────────────────────────────────────


@router.post("/send-code", response_model=dict)
async def send_verification_code(payload: EmailRequest, db: Session = Depends(get_db)):
    """Generate and send a 6-digit code to the given email.

    For the "register" purpose, the email must not already belong to a user.
    """
    if payload.purpose == "register":
        existing = db.query(User).filter(User.email == payload.email).first()
        if existing is not None:
            raise HTTPException(status_code=400, detail="该邮箱已注册")
    try:
        ttl = await request_code(payload.email, purpose=payload.purpose)  # type: ignore[arg-type]
    except CodeError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    return {"status": "sent", "expires_in": ttl}


@router.post("/register", response_model=dict)
async def register_user(user_in: UserCreate, db: Session = Depends(get_db)):
    """Register a new user after verifying their email code."""
    if db.query(User).filter(User.username == user_in.username).first():
        raise HTTPException(status_code=400, detail="该用户名已被占用")
    if db.query(User).filter(User.email == user_in.email).first():
        raise HTTPException(status_code=400, detail="该邮箱已注册")

    try:
        await verify_code(user_in.email, user_in.code, purpose="register")
    except CodeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    user = User(
        username=user_in.username,
        email=user_in.email,
        hashed_password=get_password_hash(user_in.password),
        email_verified=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"message": "User registered successfully", "user_id": user.id}


@router.post("/login", response_model=Token)
def login_access_token(
    db: Session = Depends(get_db),
    form_data: OAuth2PasswordRequestForm = Depends(),
):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="用户名或密码错误")

    access_token = create_access_token(
        data={"sub": user.username},
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    refresh_token = create_refresh_token(data={"sub": user.username})
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


@router.post("/refresh", response_model=Token)
def refresh_access_token(request: RefreshRequest, db: Session = Depends(get_db)):
    """Exchange a valid refresh token for a new access + refresh token pair."""
    credentials_exception = HTTPException(
        status_code=401,
        detail="Invalid or expired refresh token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(request.refresh_token)
        username: str = payload.get("sub")
        token_type: str = payload.get("type")
        if username is None or token_type != "refresh":
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise credentials_exception

    access_token = create_access_token(
        data={"sub": user.username},
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    refresh_token = create_refresh_token(data={"sub": user.username})
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


def _serialize_me(user: User) -> MeResponse:
    return MeResponse(
        username=user.username,
        email=user.email,
        nickname=user.nickname,
        avatar_url=user.avatar_url,
        bio=user.bio,
        email_verified=bool(user.email_verified),
        created_at=user.created_at.isoformat() if user.created_at else "",
        updated_at=user.updated_at.isoformat() if user.updated_at else "",
    )


@router.get("/me", response_model=MeResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return _serialize_me(current_user)


@router.patch("/me", response_model=MeResponse)
def update_me(
    payload: MeUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    changed = False
    if payload.nickname is not None:
        current_user.nickname = payload.nickname.strip() or None
        changed = True
    if payload.avatar_url is not None:
        current_user.avatar_url = payload.avatar_url.strip() or None
        changed = True
    if payload.bio is not None:
        current_user.bio = payload.bio.strip() or None
        changed = True
    if changed:
        db.add(current_user)
        db.commit()
        db.refresh(current_user)
    return _serialize_me(current_user)
