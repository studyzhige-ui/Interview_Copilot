"""Bearer-authenticated signalling; DTLS media cannot renew its own authority."""

import asyncio
import importlib.util
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.security import get_current_user
from app.core.rate_limit import limiter, RATE_EXPENSIVE, RATE_DEFAULT
from app.db.database import get_db
from app.models.user import User
from app.schemas.realtime import MediaOffer, MediaAnswer, MediaGeneration
from app.interviews.application import live_media_turns as application
from app.media.realtime import transport

router = APIRouter()


@router.get("/mock-interviews/media-capabilities")
def capabilities(user: User = Depends(get_current_user)):
    return {
        "enabled": settings.REALTIME_ENABLED,
        "profile": "local-network",
        "automatic_submission_default": False,
        "native_streaming_models": False,
    }


@router.post("/mock-interviews/{record_id}/media/offer", response_model=MediaAnswer)
@limiter.limit(RATE_EXPENSIVE)
async def offer(
    request: Request,
    response: Response,
    record_id: str,
    body: MediaOffer,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not settings.REALTIME_ENABLED:
        raise HTTPException(409, "实时语音未启用；仍可使用录音或文字回答。")
    if (
        settings.TRANSCRIPTION_PROVIDER != "local_qwen_asr"
        or settings.TTS_PROVIDER != "local_qwen3_tts"
    ):
        raise HTTPException(409, "实时语音需要本地 Qwen ASR 与 TTS；不会切换云端。")
    if importlib.util.find_spec("aiortc") is None:
        raise HTTPException(503, "请安装项目 realtime 依赖组。")
    try:
        transport.validate_offer(body.sdp, settings.REALTIME_ALLOWED_CIDRS)
        transport.reserve()
    except ValueError as exc:
        raise HTTPException(
            422, "实时音频连接不符合配置的本地网络或容量限制。"
        ) from exc
    actor = (user.id, user.username)
    db.close()
    lease = peer = None
    try:
        lease = await asyncio.to_thread(
            application.claim, record_id, *actor, str(body.client_session_id)
        )
        old = transport.PEERS.get(lease.id)
        if old is not None:
            await old.close()
        peer = transport.Peer(
            lease,
            application.InterviewMedia(lease),
            auto_submit=body.auto_submit,
            threshold=settings.REALTIME_VAD_THRESHOLD,
            silence_ms=settings.REALTIME_SILENCE_MS,
        )
        transport.PEERS[lease.id] = peer
        sdp = await peer.negotiate(body.sdp)
        response.headers["Cache-Control"] = "no-store"
        return MediaAnswer(session_id=lease.id, generation=lease.generation, sdp=sdp)
    except BaseException as exc:
        if peer is not None:
            await peer.close()
        elif lease is not None:
            await asyncio.to_thread(application.release, lease)
        if isinstance(exc, asyncio.CancelledError):
            raise
        raise HTTPException(
            409, "实时会话无法建立，请核对面试状态、占用及本地网络配置。"
        ) from exc
    finally:
        transport.unreserve()


def _lease(record_id, session_id, body, user):
    return application.MediaLease(
        str(session_id), body.generation, record_id, user.id, user.username
    )


@router.post("/mock-interviews/{record_id}/media/{session_id}/heartbeat")
@limiter.limit(RATE_DEFAULT)
async def heartbeat(
    request: Request,
    response: Response,
    record_id: str,
    session_id: UUID,
    body: MediaGeneration,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    lease = _lease(record_id, session_id, body, user)
    db.close()
    try:
        await asyncio.to_thread(application.renew, lease)
    except ValueError as exc:
        raise HTTPException(409, "实时会话已失效，请重新连接；不会重发回答。") from exc
    response.headers["Cache-Control"] = "no-store"
    return {"active": True}


@router.post("/mock-interviews/{record_id}/media/{session_id}/close")
async def close_media(
    record_id: str,
    session_id: UUID,
    body: MediaGeneration,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    lease = _lease(record_id, session_id, body, user)
    # Authorize independently of process-local peer identity.
    try:
        application._record(db, record_id, user.id)
        application._session(db, lease)
    except ValueError as exc:
        raise HTTPException(404, "实时会话不存在或已关闭。") from exc
    finally:
        db.close()
    peer = transport.PEERS.get(lease.id)
    if peer is not None and peer.lease.generation == lease.generation:
        await peer.close()
    else:
        await asyncio.to_thread(application.release, lease)
    return {"closed": True}
