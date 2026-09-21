"""Authenticated local WebRTC signalling; no credential in a URL or SDP."""

from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session
from app.core.security import get_current_user, oauth2_scheme
from app.core.rate_limit import limiter, RATE_EXPENSIVE, RATE_DEFAULT
from app.db.database import SessionLocal, get_db
from app.models.user import User
from app.schemas.realtime import MediaOffer, MediaAnswer, MediaPlaybackReport
from app.interviews.application.live_media import (
    LiveInterview,
    MediaConflict,
    claim,
    playback_reports,
)
from app.media.realtime.config import config
from app.media.realtime.transport import registry

router = APIRouter(tags=["live-media"])


@router.get("/mock-interviews/media-capabilities")
def media_capabilities(current_user: User = Depends(get_current_user)):
    return {
        "enabled": config.enabled,
        "transport": "webrtc-local",
        "asr": "bounded-incremental",
        "tts": "sentence-buffered",
        "max_turn_seconds": config.max_turn_seconds,
        "automatic_commit_requires_opt_in": True,
    }


@router.post("/mock-interviews/{record_id}/media/offer", response_model=MediaAnswer)
@limiter.limit(RATE_EXPENSIVE)
async def media_offer(
    request: Request,
    response: Response,
    record_id: str,
    body: MediaOffer,
    current_user: User = Depends(get_current_user),
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    if not config.enabled:
        raise HTTPException(503, "实时语音尚未启用，请使用文字或录音回答。")
    user_id, username = current_user.id, current_user.username
    db.close()  # No authentication connection is held during ICE/model initialization.

    def services_factory(connection_id):
        services = LiveInterview(
            record_id=record_id,
            user_id=user_id,
            username=username,
            token=token,
            connection_id=connection_id,
        )
        with SessionLocal() as session:
            claim(
                session,
                record_id=record_id,
                username=username,
                client_session_id=str(body.client_session_id),
                connection_id=connection_id,
            )
        return services

    try:
        result = await registry.connect(
            key=(user_id, record_id, str(body.client_session_id)),
            config=config,
            offer=body,
            services_factory=services_factory,
        )
    except MediaConflict as exc:
        raise HTTPException(409, "面试不可用或已在另一实时会话中连接。") from exc
    except (ValueError, OSError, ImportError, TimeoutError) as exc:
        raise HTTPException(
            503, "本地实时语音未就绪或连接不受支持；未切换云端，请使用文字或录音回答。"
        ) from exc
    response.headers["Cache-Control"] = "no-store"
    return result


@router.delete(
    "/mock-interviews/{record_id}/media/{client_session_id}/{connection_id}",
    status_code=204,
)
@limiter.limit(RATE_DEFAULT)
async def media_close(
    request: Request,
    response: Response,
    record_id: str,
    client_session_id: UUID,
    connection_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = current_user.id
    db.close()
    await registry.disconnect(
        (user_id, record_id, str(client_session_id)), str(connection_id)
    )


@router.get(
    "/mock-interviews/{record_id}/media/playback",
    response_model=list[MediaPlaybackReport],
)
@limiter.limit(RATE_DEFAULT)
def media_playback_reports(
    request: Request,
    response: Response,
    record_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        reports = playback_reports(
            db, record_id=record_id, username=current_user.username
        )
    except MediaConflict as exc:
        raise HTTPException(404, "面试记录不存在。") from exc
    response.headers["Cache-Control"] = "no-store"
    return [MediaPlaybackReport.model_validate(item) for item in reports]
