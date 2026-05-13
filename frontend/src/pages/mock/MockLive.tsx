import { useEffect, useRef, useState } from 'react';
import { Mic, Square, CornerUpRight, Loader2 } from 'lucide-react';
import { Btn } from '@/components/ui/Btn';
import { toast } from '@/store/uiStore';
import { useMediaRecorder } from '@/hooks/useMediaRecorder';
import { submitMockAnswer, finishMockInterview, TRANSCRIBE_AVAILABLE, transcribeAudio } from '@/api/mock';
import type { MockQuestion } from '@/types/api';

interface Turn {
  who: 'interviewer' | 'me';
  text: string;
}

interface Props {
  sessionId: string;
  initialQuestion: MockQuestion;
  onFinished: (recordId: string) => void;
}

function fmtDuration(ms: number) {
  const s = Math.floor(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

export function MockLive({ sessionId, initialQuestion, onFinished }: Props) {
  const [turns, setTurns] = useState<Turn[]>(
    initialQuestion.question ? [{ who: 'interviewer', text: initialQuestion.question }] : [],
  );
  const [typing, setTyping] = useState('');
  const [sending, setSending] = useState(false);
  const [finishing, setFinishing] = useState(false);
  const [finished, setFinished] = useState(false);
  const rec = useMediaRecorder();
  const listRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [turns]);

  const pushUserAnswer = async (answer: string) => {
    if (!answer.trim() || finished) return;
    setSending(true);
    setTurns((t) => [...t, { who: 'me', text: answer }]);
    try {
      const resp = await submitMockAnswer({ session_id: sessionId, answer });
      setTurns((t) => [...t, { who: 'interviewer', text: resp.interviewer_response }]);
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

  const onMicToggle = async () => {
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
      <div className="px-6 py-3 border-b border-stone-200 bg-white flex items-center">
        <div className="text-sm font-medium text-stone-800">模拟面试 · 进行中</div>
        <Btn
          kind="danger"
          size="sm"
          className="ml-auto"
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
            onClick={onMicToggle}
            disabled={!TRANSCRIBE_AVAILABLE || finished || transcribing}
            title={
              !TRANSCRIBE_AVAILABLE
                ? '录音转写功能即将上线'
                : rec.state === 'recording' ? '点击结束录音' : '点击开始录音'
            }
            className={[
              'w-[88px] h-[88px] rounded-full flex flex-col items-center justify-center transition-all',
              rec.state === 'recording'
                ? 'bg-danger-500 text-white animate-pulse'
                : transcribing
                ? 'bg-warning-500 text-white'
                : !TRANSCRIBE_AVAILABLE
                ? 'bg-stone-100 text-stone-300 cursor-not-allowed'
                : 'bg-primary-500 text-white hover:bg-primary-600',
            ].join(' ')}
          >
            {transcribing ? (
              <Loader2 size={28} className="animate-spin" />
            ) : rec.state === 'recording' ? (
              <Square size={28} />
            ) : (
              <Mic size={28} />
            )}
            <div className="text-[10px] mt-1">
              {transcribing
                ? '转写中…'
                : rec.state === 'recording'
                ? fmtDuration(rec.durationMs)
                : '按住说话'}
            </div>
          </button>
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
