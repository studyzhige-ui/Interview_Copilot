"""Interview HTTP boundary."""

from fastapi import APIRouter

from app.api.interviews import mock, records

router = APIRouter()
router.include_router(records.router)
router.include_router(mock.router)

__all__ = ["router"]
