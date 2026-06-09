import { useEffect, useRef, useState } from 'react';
import { Mic, Square, CornerUpRight, Loader2, Volume2, VolumeX } from 'lucide-react';
import { Btn } from '@/components/ui/Btn';
import { Modal } from '@/components/ui/Modal';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { toast } from '@/store/uiStore';
import { useMediaRecorder } from '@/hooks/useMediaRecorder';
import { useTts } from '@/hooks/useTts';
import {
  SPEECH_RECOGNITION_AVAILABLE,
  useSpeechRecognition,
} from '@/hooks/useSpeechRecognition';
import { abandonMockInterview, submitMockAnswer, finishMockInterview, TRANSCRIBE_AVAILABLE, transcribeAudio } from '@/api/mock';
import { useBlocker, useNavigate } from 'react-router-dom';
import type { VoiceMode } from './MockSetup';

// Web Speech API is reachable on Chrome/Edge **only when the host can reach
// Google's speech service** — in mainland China the recognizer silently fails
// (`network` error) and we end up with 0 finalized text. We default to the
// MediaRecorder → backend Whisper path which works offline. Users who do have
// working Web Speech can flip the toggle at the bottom of the mic area.
const STT_PREF_KEY = 'mock.sttMode'; // 'whisper' | 'native'
function loadPreferredStt(): 'whisper' | 'native' {
  try {
    const v = localStorage.getItem(STT_PREF_KEY);
    if (v === 'native' && SPEECH_RECOGNITION_AVAILABLE) return 'native';
  } catch { /* ignore */ }
  return 'whisper';
}

interface Turn {
  who: 'interviewer' | 'me';
  text: string;
}

interface Props {
  recordId: string;
  /** The opening / current interviewer line (greeting + question), one string. */
  initialQuestion: string;
  voiceMode: VoiceMode;
  onFinished: (recordId: string) => void;
  onAbandoned: () => void;
}

function fmtDuration(ms: number) {
  const s = Math.floor(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

export function MockLive({ recordId, initialQuestion, voiceMode, onFinished, onAbandoned }: Props) {
  const [turns, setTurns] = useState<Turn[]>(
    initialQuestion ? [{ who: 'interviewer', text: initialQuestion }] : [],
  );
  const [typing, setTyping] = useState('');
  const [sending, setSending] = useState(false);
  const [finishing, setFinishing] = useState(false);
  const [finished, setFinished] = useState(false);
  const [ttsMuted, setTtsMuted] = useState(false);
  const rec = useMediaRecorder();
  const listRef = useRef<HTMLDivElement | null>(null);

  const ttsEnabledByMode = voiceMode === 'voice' || voiceMode === 'hybrid';
  const ttsActive = ttsEnabledByMode && !ttsMuted;
  const tts = useTts({ enabled: ttsActive });
  const speech = useSpeechRecognition('zh-CN');
  const [sttMode, setSttMode] = useState<'whisper' | 'native'>(loadPreferredStt);
  useEffect(() => {
    try { localStorage.setItem(STT_PREF_KEY, sttMode); } catch { /* ignore */ }
  }, [sttMode]);
  const useNativeStt = sttMode === 'native' && SPEECH_RECOGNITION_AVAILABLE;

  // Auto-fall back if Web Speech errors out (commonly: `network` when Google's
  // speech endpoint is unreachable in CN). Switch the user to Whisper for the
  // rest of the session so they don't keep hitting the same wall.
  //
  // Deps destructured from speech.state — depending on the whole
  // ``speech.state`` object would re-fire this effect on every
  // interim-chunk update during listening (50+ times/sec for a
  // chatty speaker), which is wasted work. We only care about
  // ``phase`` and ``message`` here.
  // ``useSpeechRecognition`` declares ``State`` as a single shape
  // (not a discriminated union) with ``finalText``/``interim`` always
  // present and ``message`` Optional. Destructure directly — earlier
  // versions used ``'finalText' in speech.state`` guards which were
  // dead-defensive (the property is always defined).
  const speechPhase = speech.state.phase;
  const speechMessage = speech.state.message;
  const speechFinalText = speech.state.finalText;
  const speechInterim = speech.state.interim;
  useEffect(() => {
    if (useNativeStt && speechPhase === 'error') {
      const msg = speechMessage ?? '';
      if (/network|service|not-allowed/i.test(msg)) {
        toast.warn('浏览器语音识别不可达，已切到 Whisper');
        setSttMode('whisper');
      }
    }
  }, [useNativeStt, speechPhase, speechMessage]);

  // Live-stream Web Speech partials into the textarea so the user sees what
  // we're hearing in real time. final fragments accumulate in the textarea
  // for review/edit before submit.
  useEffect(() => {
    if (!useNativeStt) return;
    if (speechPhase === 'listening') {
      const combined = (speechFinalText + speechInterim).trimStart();
      setTyping(combined);
    }
  }, [useNativeStt, speechPhase, speechFinalText, speechInterim]);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [turns]);

  // Speak the opening / current interviewer line once on mount when voice
  // is on. The backend now returns the interviewer turn as a single natural
  // utterance (no spoken/question split), so we just speak it verbatim.
  const spokeInitialRef = useRef(false);
  useEffect(() => {
    if (spokeInitialRef.current) return;
    if (!ttsActive) return;
    if (!initialQuestion) return;
    spokeInitialRef.current = true;
    void tts.speak(initialQuestion);
    // tts.speak is stable for the lifetime of the useTts hook + we gate via
    // spokeInitialRef so the effect is once-only by design.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ttsActive, initialQuestion]);

  const pushUserAnswer = async (answer: string) => {
    if (!answer.trim() || finished) return;
    setSending(true);
    // Optimistic insert — the user sees their message immediately
    // rather than waiting for the backend's interviewer-response
    // round-trip.
    const optimisticTurn: Turn = { who: 'me', text: answer };
    setTurns((t) => [...t, optimisticTurn]);
    try {
      const resp = await submitMockAnswer(recordId, { answer_text: answer });
      setTurns((t) => [...t, { who: 'interviewer', text: resp.interviewer_message }]);
      if (ttsActive) void tts.speak(resp.interviewer_message);
      if (resp.is_ready_to_finish) {
        setFinished(true);
        toast.info('面试已结束，点击右上「结束面试」生成复盘记录');
      }
    } catch {
      toast.error('提交回答失败');
      // Roll back the optimistic insert so the user can retry. Pre-
      // fix the failed message just hung in the transcript with no
      // AI response — visually identical to "AI ghosted me".
      setTurns((t) => {
        const idx = t.lastIndexOf(optimisticTurn);
        if (idx === -1) return t;
        return [...t.slice(0, idx), ...t.slice(idx + 1)];
      });
    } finally {
      setSending(false);
    }
  };

  const [transcribing, setTranscribing] = useState(false);

  // Path A: Web Speech API — partials show in textarea, final commits on stop.
  const onMicToggleNative = () => {
    if (speech.state.phase === 'listening') {
      speech.stop();
      // Submit whatever we've captured. Final fragments are already in the
      // textarea via the effect above; flush after a tick so the last partial
      // becomes final before submit.
      const finalText = (speech.state.finalText + speech.state.interim).trim();
      speech.reset();
      if (finalText) {
        setTyping('');
        void pushUserAnswer(finalText);
      }
    } else {
      setTyping('');
      speech.reset();
      speech.start();
    }
  };

  // Path B: MediaRecorder → backend transcribe.
  const onMicToggleRecorder = async () => {
    if (rec.state === 'recording') {
      const blob = await rec.stop();
      if (!blob) {
        toast.warn('未捕获到音频');
        return;
      }
      if (!TRANSCRIBE_AVAILABLE) {
        toast.warn('录音转写功能即将上线，请在下方文本框输入你的回答');
        return;
      }
      setTranscribing(true);
      try {
        const text = await transcribeAudio(blob);
        if (!text.trim()) {
          toast.warn('未识别到有效语音，请重试或文字作答');
          return;
        }
        await pushUserAnswer(text);
      } catch {
        toast.error('转写失败，请重试或文字作答');
      } finally {
        setTranscribing(false);
      }
    } else {
      try {
        await rec.start();
      } catch {
        toast.error('麦克风启动失败');
      }
    }
  };

  const onMicToggle = useNativeStt ? onMicToggleNative : onMicToggleRecorder;

  // Unified state for the mic button label / styling.
  const micPhase = useNativeStt
    ? speech.state.phase === 'listening'
      ? 'recording'
      : 'idle'
    : rec.state === 'recording'
    ? 'recording'
    : transcribing
    ? 'transcribing'
    : 'idle';
  const micDisabled =
    !useNativeStt && (!TRANSCRIBE_AVAILABLE || finished || transcribing);
  const micLabel =
    micPhase === 'recording'
      ? useNativeStt
        ? '听写中…点击结束'
        : fmtDuration(rec.durationMs)
      : micPhase === 'transcribing'
      ? '转写中…'
      : useNativeStt
      ? '点击开始听写'
      : '按住说话';

  const [confirmingFinish, setConfirmingFinish] = useState(false);
  const [abandoning, setAbandoning] = useState(false);
  const answeredCount = turns.filter((t) => t.who === 'me').length;
  const navigate = useNavigate();

  // ── Navigation lock while interview is in flight ─────────────────────
  // Without this, the user clicking the sidebar away from /mock would
  // unmount MockLive, lose any local UI state (the typing draft, the
  // mic recording, the TTS queue). The run itself survives: it lives in
  // the mock_interview_runtime row + the conversation messages, so the
  // resume banner on /mock picks it up again — but the user's typing
  // buffer, the running TTS, and the active mic recorder all die on
  // unmount regardless. So we intercept navigation HERE and ask before
  // letting the unmount fire.
  //
  // We block when:
  //   - interview hasn't finished (debrief generated) yet
  //   - user isn't actively abandoning (they explicitly want to leave)
  // Both are gated by ``finished`` / ``abandoning`` flags so the
  // blocker doesn't fight the user's own "结束" / "放弃" buttons.
  const shouldBlockNav = !finished && !abandoning;
  const blocker = useBlocker(({ currentLocation, nextLocation }) =>
    shouldBlockNav && currentLocation.pathname !== nextLocation.pathname,
  );

  // ``beforeunload`` covers the close-tab / reload paths that
  // ``useBlocker`` can't see — those don't fire a route change. We can
  // only show the browser's default "Leave site?" prompt (modern
  // browsers ignore custom messages), but that's enough to save the
  // user from a fat-finger Ctrl+R.
  useEffect(() => {
    if (!shouldBlockNav) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      // Some legacy browsers still respect returnValue; setting it
      // is harmless on modern ones and required on Chrome <Dec'22.
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [shouldBlockNav]);

  const onGenerateDebrief = async () => {
    setFinishing(true);
    try {
      const r = await finishMockInterview(recordId);
      setConfirmingFinish(false);
      onFinished(r.record_id);
    } catch {
      toast.error('结束面试失败');
    } finally {
      setFinishing(false);
    }
  };

  const onAbandonInterview = async () => {
    setAbandoning(true);
    try {
      await abandonMockInterview(recordId);
      toast.success('已放弃本次面试，相关记录已删除');
      setConfirmingFinish(false);
      // Reset parent state first, THEN navigate. Without onAbandoned() the
      // parent MockPage keeps `stage='live'` so even after navigate('/mock')
      // we'd re-render MockLive on the same sessionId.
      onAbandoned();
      navigate('/mock', { replace: true });
    } catch {
      toast.error('放弃失败，请重试');
    } finally {
      setAbandoning(false);
    }
  };

  return (
    <div className="h-full flex flex-col">
      <div className="px-6 py-3 border-b border-stone-200 bg-white flex items-center gap-3">
        <div className="text-sm font-medium text-stone-800">模拟面试 · 进行中</div>
        {tts.state.phase === 'playing' && (
          <span className="text-[11px] text-primary-600 inline-flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-primary-500 animate-pulse" />
            面试官正在说话…
          </span>
        )}
        {ttsEnabledByMode && (
          <button
            onClick={() => {
              if (ttsMuted) {
                setTtsMuted(false);
              } else {
                tts.stop();
                setTtsMuted(true);
              }
            }}
            className="ml-auto inline-flex items-center gap-1 text-[12px] text-stone-600 hover:text-stone-800 px-2 py-1 rounded border border-stone-200"
            title={ttsMuted ? '开启面试官语音' : '关闭面试官语音'}
          >
            {ttsMuted ? <VolumeX size={14} /> : <Volume2 size={14} />}
            {ttsMuted ? '已静音' : '语音'}
          </button>
        )}
        <Btn
          kind="danger"
          size="sm"
          className={ttsEnabledByMode ? '' : 'ml-auto'}
          onClick={() => setConfirmingFinish(true)}
          loading={finishing}
        >
          结束面试
        </Btn>
      </div>

      <Modal
        open={confirmingFinish}
        onClose={() => !finishing && !abandoning && setConfirmingFinish(false)}
        title="结束本次面试"
        width={460}
      >
        <div className="text-stone-700 text-[15px] leading-[1.7]">
          已完成 <span className="font-semibold text-stone-900">{answeredCount}</span> 题。
          你希望如何处理这场面试？
        </div>

        <div className="mt-5 flex flex-col gap-2.5">
          <button
            type="button"
            onClick={() => setConfirmingFinish(false)}
            disabled={finishing || abandoning}
            className="text-left px-4 py-3 rounded-xl border border-stone-200 bg-white hover:bg-stone-50 hover:border-primary-300 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <div className="text-[14px] font-semibold text-stone-800">继续面试</div>
            <div className="text-[12px] text-stone-500 mt-0.5">关闭这个窗口，回到当前题目。</div>
          </button>

          <button
            type="button"
            onClick={onGenerateDebrief}
            disabled={finishing || abandoning || answeredCount === 0}
            className="text-left px-4 py-3 rounded-xl border border-primary-200 bg-primary-50 hover:bg-primary-100 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <div className="text-[14px] font-semibold text-primary-800 flex items-center gap-2">
              生成复盘
              {finishing && <Loader2 size={13} className="animate-spin" />}
            </div>
            <div className="text-[12px] text-primary-700/80 mt-0.5">
              {answeredCount === 0
                ? '至少答完一题才能生成复盘。'
                : `让 AI 批量分析这 ${answeredCount} 题，生成报告并跳转到复盘页。`}
            </div>
          </button>

          <button
            type="button"
            onClick={onAbandonInterview}
            disabled={finishing || abandoning}
            className="text-left px-4 py-3 rounded-xl border border-stone-200 bg-white hover:bg-danger-50 hover:border-danger-200 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <div className="text-[14px] font-semibold text-danger-700 flex items-center gap-2">
              放弃本次面试
              {abandoning && <Loader2 size={13} className="animate-spin" />}
            </div>
            <div className="text-[12px] text-stone-500 mt-0.5">
              不保留记录，回到模拟面试首页重新开始。
            </div>
          </button>
        </div>
      </Modal>

      <div ref={listRef} className="flex-1 min-h-0 overflow-y-auto px-6 py-8">
        <div className="max-w-[760px] mx-auto flex flex-col gap-4">
          {turns.map((t, i) => (
            <div key={i} className={`flex ${t.who === 'me' ? 'justify-end' : 'justify-start'}`}>
              <div
                className={[
                  'max-w-[80%] px-4 py-2.5 rounded-xl text-sm leading-relaxed whitespace-pre-wrap shadow-xs',
                  t.who === 'me'
                    ? 'bg-primary-500 text-white'
                    : 'bg-white border border-stone-200 text-stone-800',
                ].join(' ')}
              >
                {t.text}
              </div>
            </div>
          ))}
          {sending && (
            <div className="flex items-center gap-2 text-xs text-stone-500">
              <Loader2 size={12} className="animate-spin" />
              面试官正在回应...
            </div>
          )}
        </div>
      </div>

      <div className="border-t border-stone-200 bg-white px-6 py-4">
        <div className="max-w-[760px] mx-auto flex flex-col items-center gap-3">
          <button
            onClick={() => void onMicToggle()}
            disabled={micDisabled || finished}
            title={
              useNativeStt
                ? micPhase === 'recording' ? '点击结束听写' : '点击开始听写（浏览器原生）'
                : !TRANSCRIBE_AVAILABLE
                ? '录音转写功能即将上线'
                : micPhase === 'recording' ? '点击结束录音' : '点击开始录音'
            }
            className={[
              'w-[88px] h-[88px] rounded-full flex flex-col items-center justify-center transition-all',
              micPhase === 'recording'
                ? 'bg-danger-500 text-white animate-pulse'
                : micPhase === 'transcribing'
                ? 'bg-warning-500 text-white'
                : micDisabled
                ? 'bg-stone-100 text-stone-300 cursor-not-allowed'
                : 'bg-primary-500 text-white hover:bg-primary-600',
            ].join(' ')}
          >
            {micPhase === 'transcribing' ? (
              <Loader2 size={28} className="animate-spin" />
            ) : micPhase === 'recording' ? (
              <Square size={28} />
            ) : (
              <Mic size={28} />
            )}
            <div className="text-[10px] mt-1">{micLabel}</div>
          </button>
          {/* Mode hint + toggle. Default Whisper because Web Speech needs
            * Google's speech endpoint, which is unreachable in mainland CN. */}
          <div className="flex items-center gap-2 text-[10px] text-stone-400">
            {useNativeStt
              ? '使用浏览器原生语音识别 · 实时字幕显示在下方输入框'
              : '使用后端 Whisper · 适合国内网络环境'}
            {SPEECH_RECOGNITION_AVAILABLE && (
              <button
                type="button"
                onClick={() => setSttMode((m) => (m === 'native' ? 'whisper' : 'native'))}
                className="text-primary-600 hover:text-primary-700 underline-offset-2 hover:underline"
              >
                切换到{useNativeStt ? ' Whisper' : ' 浏览器原生'}
              </button>
            )}
          </div>
          <div className="w-full flex items-end gap-2">
            <textarea
              value={typing}
              onChange={(e) => setTyping(e.target.value)}
              rows={2}
              disabled={sending || finished}
              placeholder="输入你的回答，Ctrl+Enter 提交"
              onKeyDown={(e) => {
                if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                  e.preventDefault();
                  const t = typing;
                  setTyping('');
                  pushUserAnswer(t);
                }
              }}
              className="flex-1 resize-none border border-stone-200 rounded-md px-3 py-2 text-sm outline-none focus:border-primary-300 bg-stone-50 disabled:opacity-50"
            />
            <Btn
              size="md"
              icon={<CornerUpRight size={14} />}
              onClick={() => {
                const t = typing;
                setTyping('');
                pushUserAnswer(t);
              }}
              disabled={!typing.trim() || sending || finished}
              loading={sending}
            >
              提交
            </Btn>
          </div>
        </div>
      </div>

      {/* Navigation guard. When the user tries to leave /mock mid-
          interview, the blocker pauses the navigation and shows this
          dialog. "继续面试" calls ``blocker.reset()`` to cancel the
          navigation; "暂时离开" calls ``blocker.proceed()`` to let
          it through. The backend session stays alive — the resume
          banner on /mock will pick it up when the user returns. */}
      <ConfirmDialog
        open={blocker.state === 'blocked'}
        title="确定要离开吗？"
        description={
          `面试正在进行中（已答 ${answeredCount} 题）。离开不会丢失进度 —— ` +
          `下次回到「模拟面试」页面会看到「继续面试」的提示。如果想结束本场，` +
          `请使用右上角「结束面试」按钮。`
        }
        confirmText="暂时离开"
        cancelText="继续面试"
        onConfirm={() => blocker.proceed?.()}
        onCancel={() => blocker.reset?.()}
      />
    </div>
  );
}
