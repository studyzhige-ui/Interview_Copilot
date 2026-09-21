import asyncio
import json
from uuid import uuid4
import pytest

from app.media.realtime.vad import VoiceActivity, VoiceEvent, FRAME_BYTES
from app.media.realtime.session import RealtimeSession, speech_chunks
from app.schemas.realtime import MediaCommand

VOICE = (6000).to_bytes(2, "little", signed=True) * 320
SILENCE = b"\0" * FRAME_BYTES


class Application:
    def __init__(self):
        self.submissions = []
        self.transcriptions = []
        self.acks = []
        self.interrupted = []
        self.closed = 0
        self.pending = False
        self.question = {"id": 1, "text": "请介绍你的项目。", "speaker": "interviewer"}

    async def current(self):
        return {
            "question": self.question,
            "answer_pending": self.pending,
            "request_id": None,
            "request_status": None,
        }

    async def heartbeat(self):
        pass

    async def close(self):
        self.closed += 1

    async def transcribe(self, pcm):
        self.transcriptions.append(pcm)
        return "我的项目使用数据库事务。"

    async def synthesize(self, text):
        return b"\0\0" * 2400, 24000

    async def submit(self, question_id, text, request_id):
        self.submissions.append((question_id, text, request_id))
        self.question = {"id": 2, "text": "怎样保证幂等？", "speaker": "interviewer"}
        return {"message": self.question, "end_suggested": False}

    async def register_audio(self, question_id, text, pcm, rate):
        return str(uuid4())

    async def acknowledge(self, audio_id, samples, complete):
        self.acks.append((audio_id, samples, complete))

    async def interrupt_audio(self, audio_id):
        self.interrupted.append(audio_id)


async def until(predicate, seconds=2):
    async with asyncio.timeout(seconds):
        while not predicate():
            await asyncio.sleep(0.005)


@pytest.fixture
async def running():
    app = Application()
    events = []

    async def emit(event):
        events.append(event)

    session = RealtimeSession(app, emit)
    await session.start()
    yield session, app, events
    await session.close()
    if session.commit_task:
        await session.commit_task


def test_vad_debounce_preroll_and_exact_continuous_segment_samples():
    vad = VoiceActivity()
    for _ in range(20):
        assert not vad.feed(SILENCE)
    assert not vad.feed(VOICE)
    assert not vad.feed(VOICE)
    assert not vad.feed(VOICE)
    assert vad.feed(VOICE)[0].kind == "start"
    # 6 pre-roll silent frames + 4 onset frames; all audio survives segmentation.
    segments = []
    for _ in range(24 * 50):
        segments.extend(e.pcm for e in vad.feed(VOICE) if e.kind == "segment")
    for _ in range(45):
        for event in vad.feed(SILENCE):
            if event.kind == "final":
                segments.append(event.pcm)
    assert b"".join(segments) == SILENCE * 6 + VOICE * (4 + 24 * 50) + SILENCE * 45
    assert max(map(len, segments)) <= 16000 * 24 * 2
    assert vad.finish().kind == "empty"


def test_protocol_actions_are_strict_and_speech_split_never_loses_text():
    for value in (
        {"type": "sync", "text": "injected"},
        {"type": "commit"},
        {
            "type": "playback",
            "audio_id": str(uuid4()),
            "played_samples": True,
            "complete": True,
        },
        {"type": "commit", "draft_id": "no", "request_id": str(uuid4())},
    ):
        with pytest.raises(ValueError):
            MediaCommand.model_validate(value).checked()
    texts = [
        "中文，句子。" * 100,
        "English text? " * 100,
        "x" * 1000,
        "带空格\n换行。" * 100,
    ]
    for text in texts:
        chunks = list(speech_chunks(text))
        assert "".join(chunks) == text
        assert all(len(c) <= 180 for c in chunks)


async def test_final_draft_never_commits_without_explicit_confirmation(running):
    session, app, events = running
    for _ in range(20):
        await session.feed(VOICE)
    for _ in range(45):
        await session.feed(SILENCE)
    await until(lambda: session.draft is not None)
    assert app.submissions == []
    draft = session.draft
    request = str(uuid4())
    await session.control(
        json.dumps({"type": "commit", "draft_id": draft[0], "request_id": request})
    )
    await until(lambda: any(e["type"] == "answer" for e in events))
    assert app.submissions == [(1, draft[1], request)]
    await session.control(json.dumps({"type": "sync"}))
    assert len(app.submissions) == 1


async def test_discard_fences_a_late_asr_and_sync_never_regenerates(running):
    session, app, events = running
    gate = asyncio.Event()

    async def transcribe(pcm):
        await gate.wait()
        return "旧转写"

    app.transcribe = transcribe
    session.enqueue(VoiceEvent("final", VOICE * 10))
    await asyncio.sleep(0.01)
    await session.control('{"type":"discard"}')
    gate.set()
    await session.queue.join()
    assert session.draft is None
    assert not any(e["type"] == "final" for e in events)
    app.pending = True
    await session.control('{"type":"sync"}')
    assert session.blocked and not app.submissions


async def test_speech_interrupt_cancels_prefetch_and_tracks_played_separately(running):
    session, app, events = running
    await session.start_speech(app.question)
    await until(lambda: any(e["type"] == "audio_end" for e in events))
    audio_id = session.audio_id
    await session.control(
        json.dumps(
            {
                "type": "playback",
                "audio_id": audio_id,
                "played_samples": 500,
                "complete": False,
            }
        )
    )
    for _ in range(4):
        await session.feed(VOICE)
    assert session.audio_id is None
    assert app.acks == [(audio_id, 500, False)]
    assert app.interrupted == [audio_id]
    assert events[-1]["type"] == "speech_start"


async def test_replacement_question_cannot_retarget_an_old_draft(running):
    session, app, _ = running
    session.enqueue(VoiceEvent("final", VOICE * 10))
    await until(lambda: session.draft is not None)
    old = session.draft[0]
    app.question = {**app.question, "id": 9}
    await session.sync()
    with pytest.raises(ValueError, match="draft_not_current"):
        session.commit(old, str(uuid4()))
    assert not app.submissions


async def test_disconnect_does_not_cancel_an_accepted_business_turn(running):
    session, app, events = running
    started, finish = asyncio.Event(), asyncio.Event()

    async def submit(*args):
        started.set()
        await finish.wait()
        app.submissions.append(args)
        return {"message": {**app.question, "id": 2}, "end_suggested": False}

    app.submit = submit
    session.draft = (str(uuid4()), "final answer", 1)
    session.commit(session.draft[0], str(uuid4()))
    task = session.commit_task
    await started.wait()
    await session.close()
    count = len(events)
    finish.set()
    await task
    assert len(app.submissions) == 1 and len(events) == count
    assert app.closed == 1


async def test_overrun_and_asr_failure_never_publish_partial_success(running):
    session, app, events = running

    async def fail(pcm):
        raise RuntimeError("test provider unavailable")

    app.transcribe = fail
    session.enqueue(VoiceEvent("final", VOICE * 10))
    await session.queue.join()
    assert session.blocked and session.draft is None and not app.submissions
    assert events[-1] == {"type": "error", "code": "transcription_unconfirmed"}
    for _ in range(3):
        session.enqueue(VoiceEvent("segment", VOICE))
    with pytest.raises(ValueError, match="backpressure"):
        session.enqueue(VoiceEvent("final", VOICE))


async def test_automatic_mode_only_commits_a_finalized_utterance():
    app = Application()
    events = []

    async def emit(e):
        events.append(e)

    session = RealtimeSession(app, emit, auto_submit=True)
    await session.start()
    try:
        session.enqueue(VoiceEvent("segment", VOICE * 10))
        await session.queue.join()
        assert not app.submissions
        session.enqueue(VoiceEvent("final", VOICE * 10))
        await until(lambda: len(app.submissions) == 1)
    finally:
        await session.close()
        if session.commit_task:
            await session.commit_task
