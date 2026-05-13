import { useEffect, useRef, useState } from 'react';
import { Mic, Square, CornerUpRight, Loader2, Volume2, VolumeX } from 'lucide-react';
import { Btn } from '@/components/ui/Btn';
import { toast } from '@/store/uiStore';
import { useMediaRecorder } from '@/hooks/useMediaRecorder';
import { useTts } from '@/hooks/useTts';
import {
  SPEECH_RECOGNITION_AVAILABLE,
  useSpeechRecognition,
} from '@/hooks/useSpeechRecognition';
import { submitMockAnswer, finishMockInterview, TRANSCRIBE_AVAILABLE, transcribeAudio } from '@/api/mock';
import type { MockQuestion } from '@/types/api';
import type { VoiceMode } from './MockSetup';

// Prefer the browser's native Web Speech API when available — partial
// transcripts stream into the textarea so the user can see what's being
// captured. The MediaRecorder + /transcribe path stays as a fallback for
// browsers without speech recognition (Firefox, Safari).
const USE_NATIVE_STT = SPEECH_RECOGNITION_AVAILABLE;

interface Turn {
  who: 'interviewer' | 'me';
  text: string;
}

interface Props {
  sessionId: string;
  initialQuestion: MockQuestion;
  voiceMode: VoiceMode;
  onFinished: (recordId: string) => void;
}

function fmtDuration(ms: number) {
  const s = Math.floor(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

export function MockLive({ sessionId, initialQuestion, voiceMode, onFinished }: Props) {
  const [turns, setTurns] = useState<Turn[]>(
    initialQuestion.question ? [{ who: 'interviewer', text: initialQuestion.question }] : [],
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

  // Live-stream Web Speech partials into the textarea so the user sees what
  // we're hearing in real time. final fragments accumulate in the textarea
  // for review/edit before submit.
  useEffect(() => {
    if (!USE_NATIVE_STT) return;
    if (speech.state.phase === 'listening') {
      const combined = (speech.state.finalText + speech.state.interim).trimStart();
      setTyping(combined);
    }
  }, [speech.state]);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [turns]);

  // Speak the opening question once on mount when voice is on.
  const spokeInitialRef = useRef(false);
  useEffect(() => {
    if (spokeInitialRef.current) return;
    if (!ttsActive) return;
    if (!initialQuestion.question) return;
    spokeInitialRef.current = true;
    void tts.speak(initialQuestion.question);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ttsActive]);

  const pushUserAnswer = async (answer: string) => {
    if (!answer.trim() || finished) return;
    setSending(true);
    setTurns((t) => [...t, { who: 'me', text: answer }]);
    try {
      const resp = await submitMockAnswer({ session_id: sessionId, answer });
      setTurns((t) => [...t, { who: 'interviewer', text: resp.interviewer_response }]);
      if (ttsActive) void tts.speak(resp.interviewer_response);
      if (resp.is_finished) {
        setFinished(true);
        toast.info('面试已结束，点击右上「结束面试」生成复盘记录');
      }
    } catch {
      toast.error('提交回答失败');
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

  const onMicToggle = USE_NATIVE_STT ? onMicToggleNative : onMicToggleRecorder;

  // Unified state for the mic button label / styling.
  const micPhase = USE_NATIVE_STT
    ? speech.state.phase === 'listening'
      ? 'recording'
      : 'idle'
    : rec.state === 'recording'
    ? 'recording'
    : transcribing
    ? 'transcribing'
    : 'idle';
  const micDisabled =
    !USE_NATIVE_STT && (!TRANSCRIBE_AVAILABLE || finished || transcribing);
  const micLabel =
    micPhase === 'recording'
      ? USE_NATIVE_STT
        ? '听写中…点击结束'
        : fmtDuration(rec.durationMs)
      : micPhase === 'transcribing'
      ? '转写中…'
      : USE_NATIVE_STT
      ? '点击开始听写'
      : '按住说话';

  const onFinish = async () => {
    setFinishing(true);
    try {
      const r = await finishMockInterview(sessionId);
      onFinished(r.record_id);
    } catch {
      toast.error('结束面试失败');
    } finally {
      setFinishing(false);
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
          onClick={onFinish}
          loading={finishing}
        >
          结束面试
        </Btn>
      </div>

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
              USE_NATIVE_STT
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
          {USE_NATIVE_STT && (
            <div className="text-[10px] text-stone-400">
              使用浏览器原生语音识别 · 实时字幕显示在下方输入框
            </div>
          )}
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
    </div>
  );
}
