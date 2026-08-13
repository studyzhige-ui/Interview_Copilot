"""Narrow access-log redaction for protocol-defined sensitive query strings."""

from __future__ import annotations

import logging


_SENSITIVE_QUERY_PATHS = frozenset({"/api/v1/integrations/gmail/callback"})


class SensitiveQueryAccessLogFilter(logging.Filter):
    """Remove OAuth code/state from Uvicorn's structured access-log args."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if not isinstance(args, tuple) or len(args) < 3:
            return True
        raw_target = args[2]
        if not isinstance(raw_target, str):
            return True
        path = raw_target.partition("?")[0]
        if path not in _SENSITIVE_QUERY_PATHS:
            return True
        safe_args = list(args)
        safe_args[2] = f"{path}?[sensitive-query-redacted]"
        record.args = tuple(safe_args)
        return True


def install_sensitive_query_access_log_filter() -> None:
    logger = logging.getLogger("uvicorn.access")
    if any(isinstance(item, SensitiveQueryAccessLogFilter) for item in logger.filters):
        return
    logger.addFilter(SensitiveQueryAccessLogFilter())


__all__ = [
    "SensitiveQueryAccessLogFilter",
    "install_sensitive_query_access_log_filter",
]
