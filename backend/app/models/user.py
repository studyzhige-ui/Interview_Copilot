from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from app.db.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=True)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    email_verified = Column(Boolean, default=False, nullable=False)
    nickname = Column(String(64), nullable=True)
    # Widened to Text so we can inline ~1MB image as `data:` URL (≈1.4MB
    # base64). Plain http(s) URLs still fit fine.
    avatar_url = Column(Text, nullable=True)
    bio = Column(Text, nullable=True)
    # Per-user default for "should the QA pipeline pull this user's past
    # interview_fact memories into the LLM prompt?" Opt-in (default False)
    # for two reasons: (1) avoid surprising new users by surfacing things
    # they don't remember saying; (2) avoid contaminating answers with
    # stale facts from old sessions until the user has had a chance to
    # curate their memory list. A per-session override lives in
    # chat_sessions.session_state JSON (key ``memory_recall_enabled``);
    # service code reads the session value first and falls back here.
    memory_recall_default = Column(Boolean, default=False, nullable=False)
    # 单文档形式的用户画像。每行一条事实（"- 用户名：卷卷"）。每轮
    # 抽取时整份加载给 LLM，LLM 输出**补丁列表**（add / update / delete
    # 各行），后端按补丁原地改，未涉及的行保持字节级不变 —— 杜绝旧的
    # 多行 user_profile 表带来的语义重复（"User's name" vs "用户名"
    # 这种同义异 key 的去重难题）。空字符串 = 新用户，还没积累画像。
    user_profile_doc = Column(Text, default="", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
