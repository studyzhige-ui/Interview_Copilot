"""Real session control flow, deterministic model outputs, no paid providers."""

import asyncio
import io
import wave
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest

from app.media.realtime.config import RealtimeConfig
from app.media.realtime.session import MediaSession
from app.schemas.realtime import MediaControl


def wav():
    out = io.BytesIO()
    with wave.open(out, "wb") as handle:
        handle.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        handle.writeframes(b"\0\0" * 2400)
    return out.getvalue()


@pytest.fixture
async def live():
    services = SimpleNamespace(
        state=AsyncMock(return_value={"question_message_id": 10, "messages": []}),
        authorize=AsyncMock(),
        partial=AsyncMock(return_value="draft"),
        final=AsyncMock(return_value="my complete answer"),
        commit=AsyncMock(
            return_value={
                "message": {"id": 12, "speaker": "interviewer", "text": "Next?"},
                "end_suggested": False,
            }
        ),
        synthesize=AsyncMock(return_value=wav()),
        playback=AsyncMock(),
    )
    events = []

    async def send(value):
        events.append(value)

    detectors = SimpleNamespace(speech=lambda _: 1.0, ended=lambda _: 0.0)
    session = MediaSession(
        config=RealtimeConfig(max_turn_seconds=3),
        services=services,
        detectors=detectors,
        send=send,
    )
    await session.open()
    yield session, services, events
    await session.close()


def command(session, action, **fields):
    return MediaControl(connection_id=session.id, action=action, **fields)


async def utterance(session):
    for _ in range(10):
        await session.feed(b"\1\0" * 512)
    session.finish()
    await session.finalizing


async def test_partials_never_submit_and_final_requires_exact_commit(live):
    session, services, events = live
    await session.control(command(session, "commit", request_id="0" * 36))
    services.commit.assert_not_called()
    await utterance(session)
    assert session.phase == "awaiting_commit"
    services.commit.assert_not_called()
    final = next(event for event in events if event["type"] == "transcript.final")
    assert final["question_message_id"] == 10
    with pytest.raises(ValueError, match="stale_media_commit"):
        await session.control(command(session, "commit", request_id="0" * 36))
    await session.control(command(session, "commit", request_id=final["request_id"]))
    await session.control(command(session, "commit", request_id=final["request_id"]))
    await session.answering
    services.commit.assert_awaited_once()
    assert session.question_id == 12
    assert any(event["type"] == "answer.completed" for event in events)


async def test_model_failure_does_not_retry_or_commit_partial(live):
    session, services, events = live
    services.final.side_effect = RuntimeError("private detail")
    await utterance(session)
    assert session.phase == "blocked"
    services.final.assert_awaited_once()
    services.commit.assert_not_called()
    assert "private detail" not in str(events)


async def test_unknown_answer_remains_one_intent_and_no_reconnect_generation(live):
    session, services, events = live
    await utterance(session)
    request = session.draft["request_id"]
    services.commit.side_effect = RuntimeError("response lost after commit")
    await session.control(command(session, "commit", request_id=request))
    await session.answering
    await session.control(command(session, "commit", request_id=request))
    services.commit.assert_awaited_once()
    assert session.phase == "blocked"
    assert events[-1]["type"] == "answer.unconfirmed"
    services.state.return_value["can_listen"] = False
    await session.control(command(session, "discard"))
    assert session.phase == "blocked"


async def test_capacity_is_visible_failure_not_truncated_answer(live):
    session, services, events = live
    for _ in range(100):
        await session.feed(b"\1\0" * 512)
    assert session.phase == "blocked" and not session.audio
    assert any(event.get("code") == "turn_capacity_exceeded" for event in events)
    services.final.assert_not_called()
    services.commit.assert_not_called()


async def test_interruption_cancels_synthesis_and_old_connection_commands(live):
    session, services, events = live
    started = asyncio.Event()

    async def generating(_):
        started.set()
        await asyncio.Future()

    services.synthesize.side_effect = generating
    await session.start_speaking({"id": 10, "text": "Question."})
    await started.wait()
    # Barge-in is gated by consecutive actual speech observations.
    for _ in range(6):
        await session.feed(b"\1\0" * 512)
    assert session.speaking.cancelled()
    assert any(event["type"] == "audio.cancel" for event in events)
    services.playback.assert_awaited_once()
    report = services.playback.call_args.args[0]
    assert report["status"] == "interrupted" and report["client_reported_samples"] == 0
    await session.control(MediaControl(connection_id="0" * 36, action="finish"))
    assert session.phase == "listening"


async def test_playback_is_ordered_bounded_and_reports_are_not_generation(live):
    session, services, events = live
    await session.start_speaking({"id": 10, "text": "First. Second."})
    for _ in range(20):
        await asyncio.sleep(0)
        if any(event["type"] == "audio.end" for event in events):
            break
    services.synthesize.assert_awaited_once()
    playback = session.playback
    assert playback.generated == playback.delivered == 2400 and playback.reported == 0
    with pytest.raises(ValueError, match="invalid_playback_ack"):
        await session.control(
            command(session, "ack", playback_id=playback.id, samples=2401)
        )
    await session.control(
        command(session, "ack", playback_id=playback.id, samples=2400)
    )
    for _ in range(20):
        await asyncio.sleep(0)
        if services.synthesize.await_count == 2:
            break
    await asyncio.sleep(0)
    await session.control(
        command(session, "ack", playback_id=playback.id, samples=4800)
    )
    await session.speaking
    report = services.playback.call_args.args[0]
    assert report["generated_samples"] == report["client_reported_samples"] == 4800
    assert report["status"] == "completed"


async def test_close_drops_pending_draft_and_cancels_tasks(live):
    session, services, _ = live
    await utterance(session)
    await session.close()
    assert not session.audio and session.draft is None
    assert all(task.done() for task in session.tasks)
    services.commit.assert_not_called()


async def test_resumed_speech_fences_late_semantic_end_result(live):
    import threading

    session, services, events = live
    started, release = threading.Event(), threading.Event()

    def endpoint(_):
        started.set()
        assert release.wait(5)
        return 1.0

    session.detectors.ended = endpoint
    for _ in range(10):
        await session.feed(b"\1\0" * 512)
    session.detectors.speech = lambda _: 0.0
    try:
        for _ in range(28):
            await session.feed(b"\0\0" * 512)
        assert await asyncio.to_thread(started.wait, 2)
        session.detectors.speech = lambda _: 1.0
        await session.feed(b"\1\0" * 512)
        release.set()
        await session.endpoint
        assert session.phase == "listening"
        services.final.assert_not_called()
        services.commit.assert_not_called()
    finally:
        release.set()
