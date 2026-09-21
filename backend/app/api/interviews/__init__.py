"""Interview HTTP boundary."""

from fastapi import APIRouter

from app.api.interviews import mock, records, transcripts, realtime, preparation

router = APIRouter()
router.include_router(records.router)
router.include_router(mock.router)
router.include_router(transcripts.router)
router.include_router(realtime.router)
router.include_router(preparation.router)

__all__ = ["router"]
