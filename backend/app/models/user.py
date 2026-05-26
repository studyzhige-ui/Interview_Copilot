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
    # Per-user default for the GLOBAL (cross-session) memory toggle.
    # When False, the LLM does NOT see the v3 memory bundle
    # (user_profile + knowledge / strategy / habit docs) — only
    # session-local context (recent_turns, session_state, debrief
    # reference) reaches the prompt. Matches Claude Code's
    # ``isAutoMemoryEnabled`` semantics — global memdir off; per-
    # session context untouched.
    #
    # Storage is unaffected: this is an INJECTION gate. The user's
    # personalization page can still read user_profile_doc / docs from
    # the DB directly to render the user's own memory inventory.
    #
    # Opt-in (default False) for new users — they get vanilla chat
    # until they curate their memory and explicitly opt in.
    #
    # A per-session override lives in chat_sessions.session_state JSON
    # (key ``global_memory_enabled``); service code reads the session
    # value first and falls back here.
    global_memory_enabled = Column(Boolean, default=False, nullable=False)
    # 单文档形式的用户画像。每行一条事实（"- 用户名：卷卷"）。每轮
    # 抽取时整份加载给 LLM，LLM 输出**补丁列表**（add / update / delete
    # 各行），后端按补丁原地改，未涉及的行保持字节级不变 —— 杜绝旧的
    # 多行 user_profile 表带来的语义重复（"User's name" vs "用户名"
    # 这种同义异 key 的去重难题）。空字符串 = 新用户，还没积累画像。
    user_profile_doc = Column(Text, default="", nullable=False)
    # When the nightly dreaming worker last consolidated this user's
    # memory docs. NULL = never dreamed. Used as the "cursor" by the
    # autoDream gate logic: the next nightly run only fires for this
    # user if (a) it's been >=24h since this timestamp AND (b) the
    # user has accumulated enough new chat activity since then. See
    # ``app.services.memory.dreaming_worker``.
    last_dreamed_at = Column(DateTime, nullable=True)
    # Per-user runtime model selection. JSON-encoded dict mapping role
    # (``primary`` / ``fast`` / ``agent`` / ``mock_interview``) → model
    # profile id. NULL = use ROLE_DEFAULTS. Pre-fix this lived in a
    # shared ``data/runtime/model_selection.json`` single file that
    # every process read — User A's PUT /models/runtime would change
    # B's next chat (cross-tenant model + billing). Stored per-user
    # so each account's choice only affects their own LLM calls.
    model_selection_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
