from __future__ import annotations

import logging

from app.core.http_log_redaction import SensitiveQueryAccessLogFilter


def _record(target: str) -> logging.LogRecord:
    return logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1", "GET", target, "1.1", 200),
        exc_info=None,
    )


def test_gmail_callback_code_and_state_are_removed_from_uvicorn_access_log():
    secret_code = "oauth-code-secret"
    secret_state = "oauth-state-secret"
    record = _record(
        f"/api/v1/integrations/gmail/callback?code={secret_code}&state={secret_state}"
    )

    assert SensitiveQueryAccessLogFilter().filter(record) is True
    rendered = record.getMessage()

    assert "sensitive-query-redacted" in rendered
    assert secret_code not in rendered
    assert secret_state not in rendered


def test_unrelated_query_string_remains_observable():
    record = _record("/api/v1/jobs?q=backend")
    SensitiveQueryAccessLogFilter().filter(record)
    assert "/api/v1/jobs?q=backend" in record.getMessage()
