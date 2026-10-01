"""Map explicit application failures to HTTP; unknown failures are not hidden."""

from contextlib import contextmanager
from fastapi import HTTPException
from app.core.command_errors import CommandError


@contextmanager
def command_errors():
    try:
        yield
    except CommandError as exc:
        codes = {
            "invalid": 400,
            "not_found": 404,
            "conflict": 409,
            "unavailable": 503,
            "failed": 500,
        }
        raise HTTPException(status_code=codes[exc.kind], detail=exc.message) from exc
