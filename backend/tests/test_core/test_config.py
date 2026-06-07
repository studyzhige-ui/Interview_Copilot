"""Tests for app.core.config — Settings shape, path derivation, prod-safety check."""
from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest

from app.core.config import (
    Settings,
    _default_app_data_dir,
    _validate_production_safety,
    settings,
)


# ── Settings shape ───────────────────────────────────────────────────────
def test_settings_has_required_attributes():
    required = [
        "DATABASE_URL", "APP_DATA_DIR", "DB_DIR", "CHROMA_DB_DIR",
        "DOCSTORE_DIR", "CACHE_DIR", "LOG_DIR", "EVAL_DIR", "STORAGE_DIR",
        "EMBEDDING_MODEL", "RERANKER_MODEL", "SECRET_KEY",
        "REDIS_URL", "S3_BUCKET_NAME", "ALGORITHM",
        "ACCESS_TOKEN_EXPIRE_MINUTES", "REFRESH_TOKEN_EXPIRE_MINUTES",
    ]
    for attr in required:
        assert hasattr(settings, attr), f"Settings missing: {attr}"


def test_embedding_model_field_name_not_legacy():
    """Guard against a regression of the EMBEDDING_MODEL → EMBEDDING_MODEL_ID rename."""
    s = Settings()
    assert hasattr(s, "EMBEDDING_MODEL")
    assert not hasattr(s, "EMBEDDING_MODEL_ID"), \
        "Settings still exposes the legacy EMBEDDING_MODEL_ID name"
    assert isinstance(s.EMBEDDING_MODEL, str) and s.EMBEDDING_MODEL


# ── Path derivation ──────────────────────────────────────────────────────
def test_default_app_data_dir_points_to_project_root(monkeypatch):
    monkeypatch.delenv("APP_DATA_DIR", raising=False)
    result = _default_app_data_dir()
    assert Path(result).is_absolute()
    assert result.endswith("data")


def test_app_data_dir_respects_env_override(monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", "/custom/test/path")
    assert _default_app_data_dir() == "/custom/test/path"


def test_sub_dirs_are_children_of_app_data_dir():
    base = Path(settings.APP_DATA_DIR)
    for attr in ["DB_DIR", "CACHE_DIR", "LOG_DIR", "EVAL_DIR", "STORAGE_DIR"]:
        child = Path(getattr(settings, attr))
        assert str(child).startswith(str(base)), \
            f"{attr}={child} is not under APP_DATA_DIR={base}"


def test_subdir_field_validator_picks_named_subfolders(monkeypatch):
    """The _fill_data_subdirs validator should map fields to specific subdir names."""
    monkeypatch.setenv("APP_DATA_DIR", str(Path("/tmp/icp-test")))
    # Explicitly clear so the validator uses the default.
    for v in ["DB_DIR", "CHROMA_DB_DIR", "DOCSTORE_DIR",
              "CACHE_DIR", "LOG_DIR", "EVAL_DIR", "STORAGE_DIR"]:
        monkeypatch.delenv(v, raising=False)
    s = Settings()
    assert s.DB_DIR.endswith("databases")
    assert "chroma" in s.CHROMA_DB_DIR
    assert s.DOCSTORE_DIR.endswith("docstore")
    assert s.CACHE_DIR.endswith("cache")
    assert s.LOG_DIR.endswith("logs")
    assert s.EVAL_DIR.endswith("evaluation")
    assert s.STORAGE_DIR.endswith("storage")


# ── RAG numeric sanity ───────────────────────────────────────────────────
def test_rag_score_thresholds_are_valid():
    assert 0 < settings.RAG_MIN_SCORE <= 1.0
    assert 0 < settings.RAG_FALLBACK_MIN_SCORE <= settings.RAG_MIN_SCORE
    assert 0 < settings.RAG_LEXICAL_FALLBACK_MIN_OVERLAP <= 1.0
    assert settings.VECTOR_TOP_K > 0
    assert settings.BM25_TOP_K > 0
    assert settings.FUSION_TOP_K > 0
    assert settings.RERANK_TOP_N > 0


# ── _validate_production_safety ──────────────────────────────────────────
def _make_settings(**overrides) -> Settings:
    """Build a Settings without re-reading .env by handing values directly."""
    return Settings(**overrides)


def test_validate_production_safety_dev_uses_info_for_bundled_creds(caplog):
    s = _make_settings(
        SECRET_KEY="a-real-key-not-on-blocklist-xyz",
        DATABASE_URL="postgresql://postgres:postgres@localhost:5432/x",
        AWS_ACCESS_KEY_ID="minioadmin",
        AWS_SECRET_ACCESS_KEY="minioadmin",
        ENVIRONMENT="local",
    )
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="app.core.config"):
        _validate_production_safety(s)
    # One INFO line, no per-finding WARNINGs.
    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    warn_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert info_records, "expected an INFO line about bundled dev credentials"
    assert any("bundled dev credentials" in r.getMessage() for r in info_records)
    assert not warn_records, f"unexpected warnings: {[r.getMessage() for r in warn_records]}"


def test_validate_production_safety_prod_emits_error_per_finding(caplog):
    """Prod-like env with bundled DB/MinIO creds: each finding logs at
    ERROR level (changed from WARNING after we made SECRET_KEY a hard
    raise — the other findings are now the loudest non-fatal signal)."""
    s = _make_settings(
        SECRET_KEY="a-real-key-not-on-blocklist-xyz",
        DATABASE_URL="postgresql://postgres:postgres@localhost:5432/x",
        AWS_ACCESS_KEY_ID="minioadmin",
        AWS_SECRET_ACCESS_KEY="minioadmin",
        ENVIRONMENT="prod",
        # TRUSTED_PROXIES set to a sane prod value so this test only
        # exercises the DB / MinIO findings — the TRUSTED_PROXIES
        # finding has its own dedicated test below.
        TRUSTED_PROXIES="127.0.0.1",
    )
    caplog.clear()
    with caplog.at_level(logging.ERROR, logger="app.core.config"):
        _validate_production_safety(s)
    err_msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    # Three findings → three ERROR lines (DB, MinIO user, MinIO pass).
    blocker_msgs = [m for m in err_msgs if "PRODUCTION BLOCKER" in m]
    assert len(blocker_msgs) == 3, f"expected 3 blockers, got: {blocker_msgs}"
    assert any("DATABASE_URL" in m for m in blocker_msgs)
    assert any("AWS_ACCESS_KEY_ID" in m for m in blocker_msgs)
    assert any("AWS_SECRET_ACCESS_KEY" in m for m in blocker_msgs)


def test_validate_production_safety_secret_key_raises_in_prod():
    """A placeholder SECRET_KEY in prod must refuse to start (RuntimeError).

    JWT signing + Fernet decryption both depend on a real SECRET_KEY;
    booting with a default value is cryptographically catastrophic, so
    we treat it as fatal rather than logging and continuing."""
    s = _make_settings(
        SECRET_KEY="change-me-for-local-development",
        DATABASE_URL="postgresql://prod_user:strong_pw@db:5432/x",
        AWS_ACCESS_KEY_ID="rotated",
        AWS_SECRET_ACCESS_KEY="rotated",
        ENVIRONMENT="production",
    )
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        _validate_production_safety(s)


def test_validate_production_safety_secret_key_always_warns(caplog):
    """A placeholder SECRET_KEY is WARNING-level even in dev."""
    s = _make_settings(
        SECRET_KEY="change-me-for-local-development",
        DATABASE_URL="postgresql://prod_user:strong_pw@db:5432/x",
        AWS_ACCESS_KEY_ID="rotated_id",
        AWS_SECRET_ACCESS_KEY="rotated_secret",
        ENVIRONMENT="local",
    )
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="app.core.config"):
        _validate_production_safety(s)
    warn_msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("SECRET_KEY" in m and "insecure default" in m for m in warn_msgs), warn_msgs


def test_validate_production_safety_clean_settings_emit_nothing(caplog):
    s = _make_settings(
        SECRET_KEY="random-strong-secret-12345xyz",
        DATABASE_URL="postgresql://prod_user:strong_pw@db:5432/x",
        AWS_ACCESS_KEY_ID="AKIA_ROTATED",
        AWS_SECRET_ACCESS_KEY="rotated_secret_xyz",
        ENVIRONMENT="prod",
        TRUSTED_PROXIES="127.0.0.1",
    )
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="app.core.config"):
        _validate_production_safety(s)
    msgs = [r.getMessage() for r in caplog.records]
    assert not msgs, f"expected silence, got {msgs}"


def test_validate_production_safety_warns_on_empty_trusted_proxies_in_prod(caplog):
    """TRUSTED_PROXIES empty in prod = silent rate-limit collapse.

    Without ProxyHeadersMiddleware, every request behind nginx/ALB
    looks like it came from the proxy IP — slowapi's per-IP key_func
    and the verification-code IP-lockout both degrade to one global
    counter, so one attacker burns the 5/min auth quota for everyone.
    The startup-time finding is the only thing standing between a
    misconfigured deploy and a silently broken security boundary."""
    s = _make_settings(
        SECRET_KEY="random-strong-secret-12345xyz",
        DATABASE_URL="postgresql://prod_user:strong_pw@db:5432/x",
        AWS_ACCESS_KEY_ID="AKIA_ROTATED",
        AWS_SECRET_ACCESS_KEY="rotated_secret_xyz",
        ENVIRONMENT="prod",
        TRUSTED_PROXIES="",
    )
    caplog.clear()
    with caplog.at_level(logging.ERROR, logger="app.core.config"):
        _validate_production_safety(s)
    err_msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert any("TRUSTED_PROXIES" in m and "PRODUCTION BLOCKER" in m for m in err_msgs), err_msgs


def test_validate_production_safety_dev_silent_on_empty_trusted_proxies(caplog):
    """Dev (ENVIRONMENT=local) must NOT warn about empty
    TRUSTED_PROXIES — direct-connect doesn't need the rewrite, and
    nagging on every local startup would train developers to
    ignore the warning."""
    s = _make_settings(
        SECRET_KEY="random-strong-secret-12345xyz",
        DATABASE_URL="postgresql://prod_user:strong_pw@db:5432/x",
        AWS_ACCESS_KEY_ID="AKIA_ROTATED",
        AWS_SECRET_ACCESS_KEY="rotated_secret_xyz",
        ENVIRONMENT="local",
        TRUSTED_PROXIES="",
    )
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="app.core.config"):
        _validate_production_safety(s)
    msgs = [r.getMessage() for r in caplog.records]
    assert not any("TRUSTED_PROXIES" in m for m in msgs), msgs


@pytest.mark.parametrize("env", ["staging", "prod", "production", "PROD", "  Production  "])
def test_validate_production_safety_treats_prod_aliases_as_prodlike(caplog, env):
    """Various ways of spelling "production" should all trigger the ERROR
    logging path for non-SECRET_KEY findings."""
    s = _make_settings(
        SECRET_KEY="a-real-key-not-on-blocklist-xyz",
        DATABASE_URL="postgresql://postgres:postgres@db:5432/x",
        AWS_ACCESS_KEY_ID="rotated",
        AWS_SECRET_ACCESS_KEY="rotated",
        ENVIRONMENT=env,
        TRUSTED_PROXIES="127.0.0.1",
    )
    caplog.clear()
    with caplog.at_level(logging.ERROR, logger="app.core.config"):
        _validate_production_safety(s)
    assert any("PRODUCTION BLOCKER" in r.getMessage()
               for r in caplog.records if r.levelno == logging.ERROR)
