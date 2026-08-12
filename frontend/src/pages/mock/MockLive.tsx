import { useEffect, useRef, useState } from 'react';
import { Mic, Square, CornerUpRight, Loader2, Volume2, VolumeX } from 'lucide-react';
import { Btn } from '@/components/ui/Btn';
import { Modal } from '@/components/ui/Modal';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { toast } from '@/store/uiStore';
import { useMediaRecorder } from '@/hooks/useMediaRecorder';
import { useTts } from '@/hooks/useTts';
import {
  abandonMockInterview,
  finishMockInterview,
  getMockLiveState,
  prepareMockAnswerAudio,
  submitMockAnswer,
} from '@/api/mock';
import { extractErr } from '@/api/client';
import { useBlocker, useNavigate } from 'react-router-dom';
import type { TtsVoice } from './MockSetup';
import type { MockLiveMessage } from '@/types/api';
import { useIsMounted } from '@/hooks/useIsMounted';

type LiveOperation =
  | 'idle'
  | 'submitting'
  | 'recovering'
  | 'finishing'
  | 'abandoning'
  | 'completed';

interface PendingAnswer {
  text: string;
  audioAssetId?: string;
  questionMessageId: number;
  optimisticMessageId: number;
}

interface VoiceDraft {
  audioAssetId: string;
}

interface Props {
  recordId: string;
  initialMessages?: MockLiveMessage[];
  ttsVoice: TtsVoice;
  onFinished: (recordId: string) => void;
  onAbandoned: () => void;
}

function fmtDuration(ms: number) {
  const s = Math.floor(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

function findLatestInterviewer(messages: MockLiveMessage[]) {
  return [...messages]
    .reverse()
    .find((message) => message.speaker === 'interviewer');
}

export function MockLive({
  recordId,
  initialMessages = [],
  ttsVoice,
  onFinished,
  onAbandoned,
}: Props) {
  const [messages, setMessages] = useState<MockLiveMessage[]>(initialMessages);
  const [typing, setTyping] = useState('');
  const [operation, setOperation] = useState<LiveOperation>(
    initialMessages.length > 0 ? 'idle' : 'recovering',
  );
  const [recoveryNotice, setRecoveryNotice] = useState<string | null>(null);
  const pendingAnswerRef = useRef<PendingAnswer | null>(null);
  const isMounted = useIsMounted();
  // The model may suggest wrapping up, but the candidate keeps control of
  // when the interview actually ends.
  const [endSuggested, setEndSuggested] = useState(false);
  const [ttsMuted, setTtsMuted] = useState(false);
  const [voiceDraft, setVoiceDraft] = useState<VoiceDraft | null>(null);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const [retryRecording, setRetryRecording] = useState<Blob | null>(null);
  const rec = useMediaRecorder();
  const listRef = useRef<HTMLDivElement | null>(null);

  const ttsActive = !ttsMuted;
  const tts = useTts({ enabled: ttsActive, voice: ttsVoice });

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [messages, recoveryNotice]);

  // Every server message has a stable id, so fresh starts, resumed sessions
  // and recovered requests all use the same once-only TTS rule.
  const spokenMessageIdRef = useRef<number | null>(null);
  const latestInterviewerMessage = findLatestInterviewer(messages);
  useEffect(() => {
    if (!ttsActive || !latestInterviewerMessage) return;
    if (spokenMessageIdRef.current === latestInterviewerMessage.id) return;
    spokenMessageIdRef.current = latestInterviewerMessage.id;
    void tts.speak(latestInterviewerMessage.text);
    // The message id gate makes this effect once-only per interviewer turn.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ttsActive, latestInterviewerMessage?.id]);

  const syncMessages = async () => {
    const state = await getMockLiveState(recordId);
    if (isMounted.current) setMessages(state.messages);
    return state.messages;
  };

  useEffect(() => {
    if (initialMessages.length > 0) return;
    let active = true;
    getMockLiveState(recordId)
      .then((state) => {
        if (active) {
          setMessages(state.messages);
          setRecoveryNotice(null);
        }
      })
      .catch(() => {
        if (active) {
          setRecoveryNotice('暂时无法恢复面试现场，请检查连接后重试。');
        }
      })
      .finally(() => {
        if (active) setOperation('idle');
      });
    return () => { active = false; };
  }, [initialMessages.length, recordId]);

  const acceptInterviewerMessage = (
    message: MockLiveMessage,
    endSuggested: boolean,
  ) => {
    setMessages((current) => [...current, message]);
    pendingAnswerRef.current = null;
    setVoiceDraft(null);
    setVoiceError(null);
    setRetryRecording(null);
    setRecoveryNotice(null);
    if (endSuggested) {
      setEndSuggested(true);
      toast.info('面试官觉得可以收尾了——你可以继续追问，或点右上「结束面试」生成复盘');
    }
  };

  const recoverPendingAnswer = async (pending: PendingAnswer) => {
    setOperation('recovering');
    try {
      let canonical = await syncMessages();
      const latest = findLatestInterviewer(canonical);
      if (latest && latest.id !== pending.questionMessageId) {
        pendingAnswerRef.current = null;
        setVoiceDraft(null);
        setRecoveryNotice(null);
        return;
      }

      const last = canonical.at(-1);
      if (last?.speaker !== 'candidate' || last.text.trim() !== pending.text.trim()) {
        pendingAnswerRef.current = null;
        setTyping((current) => current.trim() ? current : pending.text);
        setVoiceDraft(
          pending.audioAssetId ? { audioAssetId: pending.audioAssetId } : null,
        );
        setRecoveryNotice('回答没有成功提交，内容已恢复到输入框。');
        return;
      }

      // The server has already persisted this answer (and consumed its audio
      // asset). Keep the id only in ``pending`` for response recovery; it must
      // not leak into whatever the user types next.
      setVoiceDraft(null);

      try {
        const response = await submitMockAnswer(recordId, {
          answer_text: pending.text,
          ...(pending.audioAssetId
            ? { answer_audio_file_asset_id: pending.audioAssetId }
            : {}),
          question_message_id: pending.questionMessageId,
        });
        setMessages([...canonical, response.message]);
        pendingAnswerRef.current = null;
        setVoiceDraft(null);
        setRecoveryNotice(null);
        if (response.end_suggested) setEndSuggested(true);
        return;
      } catch {
        // The original request may still be finishing. Give it one short
        // reconciliation window before asking the user to do anything.
        await new Promise((resolve) => setTimeout(resolve, 600));
        canonical = await syncMessages();
        const recovered = findLatestInterviewer(canonical);
        if (recovered && recovered.id !== pending.questionMessageId) {
          pendingAnswerRef.current = null;
          setVoiceDraft(null);
          setRecoveryNotice(null);
          return;
        }
      }

      setRecoveryNotice(
        '你的回答已经保留，但面试官暂时没有响应。可以重新连接，或稍后继续面试。',
      );
    } catch {
      setRecoveryNotice(
        '连接暂时中断，回答仍保留在当前页面。恢复连接后可以继续同步。',
      );
    } finally {
      if (isMounted.current) setOperation('idle');
    }
  };

  const pushUserAnswer = async (answer: string, audioAssetId?: string) => {
    const text = answer.trim();
    if (!text || operation !== 'idle') return;
    const question = findLatestInterviewer(messages);
    if (!question) {
      setRecoveryNotice('当前问题尚未恢复，请先重新连接面试现场。');
      return;
    }

    const pending: PendingAnswer = {
      text,
      ...(audioAssetId ? { audioAssetId } : {}),
      questionMessageId: question.id,
      optimisticMessageId: -Date.now(),
    };
    pendingAnswerRef.current = pending;
    setTyping('');
    setRecoveryNotice(null);
    setOperation('submitting');
    setMessages((current) => [
      ...current,
      { id: pending.optimisticMessageId, speaker: 'candidate', text },
    ]);
    try {
      const response = await submitMockAnswer(recordId, {
        answer_text: text,
        ...(audioAssetId ? { answer_audio_file_asset_id: audioAssetId } : {}),
        question_message_id: question.id,
      });
      acceptInterviewerMessage(response.message, response.end_suggested);
      setOperation('idle');
    } catch {
      await recoverPendingAnswer(pending);
    }
  };

  const [inputPhase, setInputPhase] = useState<'idle' | 'preparing'>('idle');

  const prepareRecording = async (blob: Blob) => {
    setRetryRecording(blob);
    setVoiceError(null);
    setInputPhase('preparing');
    try {
      const prepared = await prepareMockAnswerAudio(recordId, blob);
      setTyping(prepared.text);
      setVoiceDraft({ audioAssetId: prepared.audio_file_asset_id });
      setRetryRecording(null);
    } catch (error) {
      setVoiceError(
        extractErr(error, '转写失败，录音仍保留在当前页面，请重试或改用文字回答'),
      );
    } finally {
      if (isMounted.current) setInputPhase('idle');
    }
  };

  const onMicToggle = async () => {
    if (operation !== 'idle' || inputPhase === 'preparing') return;
    if (rec.state === 'recording') {
      const blob = await rec.stop();
      if (!blob) {
        setVoiceError('没有录到有效声音，请重新录制或改用文字回答。');
        return;
      }
      await prepareRecording(blob);
    } else {
      setVoiceError(null);
      tts.stop();
      await rec.start();
    }
  };

  const micPhase = rec.state === 'recording'
    ? 'recording'
    : inputPhase === 'preparing' || rec.state === 'stopping'
    ? 'preparing'
    : rec.state === 'requesting'
    ? 'requesting'
    : 'idle';
  const inputBusy = micPhase !== 'idle';
  const operationBusy = operation !== 'idle';
  const canSubmit = !operationBusy && !inputBusy;
  const micDisabled = operationBusy || micPhase === 'preparing' || micPhase === 'requesting';
  const modalBusy = operation === 'finishing' || operation === 'abandoning';
  const micLabel =
    micPhase === 'recording'
      ? fmtDuration(rec.durationMs)
      : micPhase === 'preparing'
      ? '正在转写…'
      : micPhase === 'requesting'
      ? '正在连接…'
      : '点击录音';

  const [confirmingFinish, setConfirmingFinish] = useState(false);
  const answeredCount = messages.filter((message) => message.speaker === 'candidate').length;
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
  const shouldBlockNav = operation !== 'completed' && operation !== 'abandoning';
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
    if (operation !== 'idle' || inputBusy) return;
    tts.stop();
    setOperation('finishing');
    try {
      const r = await finishMockInterview(recordId);
      setConfirmingFinish(false);
      setOperation('completed');
      onFinished(r.record_id);
    } catch (e) {
      // A stale tab's finish lands 409 with an actionable server message
      // (复盘可能已在生成或已完成) — show it instead of a generic failure.
      toast.error(extractErr(e, '结束面试失败'));
      if (isMounted.current) setOperation('idle');
    }
  };

  const onAbandonInterview = async () => {
    if (operation !== 'idle') return;
    tts.stop();
    setOperation('abandoning');
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
      if (isMounted.current) setOperation('idle');
    }
  };

  const retryRecovery = async () => {
    const pending = pendingAnswerRef.current;
    if (pending) {
      await recoverPendingAnswer(pending);
      return;
    }
    setOperation('recovering');
    try {
      await syncMessages();
      setRecoveryNotice(null);
    } catch {
      setRecoveryNotice('仍然无法连接面试现场，请稍后再试。');
    } finally {
      if (isMounted.current) setOperation('idle');
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
        {tts.state.phase === 'error' && (
          <span className="text-[11px] text-amber-700">
            语音播放失败，文字内容不受影响
          </span>
        )}
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
        <Btn
          kind="danger"
          size="sm"
          onClick={() => {
            tts.stop();
            setConfirmingFinish(true);
          }}
          disabled={!canSubmit}
          loading={operation === 'finishing'}
        >
          结束面试
        </Btn>
      </div>

      {endSuggested && (
        // Advisory only (MOCK-5): the LLM thinks the interview covered
        // enough. The candidate stays in control — keep answering or finish.
        <div className="mx-4 mt-2 flex items-center gap-2 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
          <span className="text-xs text-amber-900 flex-1">
            本次面试的主要考察已经完成。你可以继续交流，也可以结束并生成复盘。
          </span>
          <button
            type="button"
            onClick={() => setConfirmingFinish(true)}
            className="text-xs font-medium text-amber-900 hover:text-amber-950 shrink-0"
          >
            结束并生成复盘
          </button>
          <button
            type="button"
            onClick={() => setEndSuggested(false)}
            className="text-xs text-amber-700 hover:text-amber-900 shrink-0"
          >
            继续面试
          </button>
        </div>
      )}

      <Modal
        open={confirmingFinish}
        onClose={() => !modalBusy && setConfirmingFinish(false)}
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
            disabled={modalBusy}
            className="text-left px-4 py-3 rounded-xl border border-stone-200 bg-white hover:bg-stone-50 hover:border-primary-300 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <div className="text-[14px] font-semibold text-stone-800">继续面试</div>
            <div className="text-[12px] text-stone-500 mt-0.5">关闭这个窗口，回到当前题目。</div>
          </button>

          <button
            type="button"
            onClick={onGenerateDebrief}
            disabled={modalBusy || answeredCount === 0}
            className="text-left px-4 py-3 rounded-xl border border-primary-200 bg-primary-50 hover:bg-primary-100 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <div className="text-[14px] font-semibold text-primary-800 flex items-center gap-2">
              生成复盘
              {operation === 'finishing' && <Loader2 size={13} className="animate-spin" />}
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
            disabled={modalBusy}
            className="text-left px-4 py-3 rounded-xl border border-stone-200 bg-white hover:bg-danger-50 hover:border-danger-200 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <div className="text-[14px] font-semibold text-danger-700 flex items-center gap-2">
              放弃本次面试
              {operation === 'abandoning' && <Loader2 size={13} className="animate-spin" />}
            </div>
            <div className="text-[12px] text-stone-500 mt-0.5">
              不保留记录，回到模拟面试首页重新开始。
            </div>
          </button>
        </div>
      </Modal>

      <div ref={listRef} className="flex-1 min-h-0 overflow-y-auto px-6 py-8">
        <div className="max-w-[760px] mx-auto flex flex-col gap-4">
          {messages.map((message) => (
            <div
              key={message.id}
              className={`flex ${message.speaker === 'candidate' ? 'justify-end' : 'justify-start'}`}
            >
              <div
                className={[
                  'max-w-[80%] px-4 py-2.5 rounded-xl text-sm leading-relaxed whitespace-pre-wrap shadow-xs',
                  message.speaker === 'candidate'
                    ? 'bg-primary-500 text-white'
                    : 'bg-white border border-stone-200 text-stone-800',
                ].join(' ')}
              >
                {message.text}
              </div>
            </div>
          ))}
          {(operation === 'submitting' || operation === 'recovering') && (
            <div className="flex items-center gap-2 text-xs text-stone-500">
              <Loader2 size={12} className="animate-spin" />
              {operation === 'recovering' ? '正在恢复面试现场…' : '面试官正在回应…'}
            </div>
          )}
          {recoveryNotice && operation === 'idle' && (
            <div className="flex items-center gap-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2">
              <span className="flex-1 text-xs leading-5 text-amber-900">{recoveryNotice}</span>
              <button
                type="button"
                onClick={() => void retryRecovery()}
                className="shrink-0 text-xs font-medium text-amber-800 hover:text-amber-950"
              >
                重新连接
              </button>
              <button
                type="button"
                onClick={() => navigate('/mock')}
                className="shrink-0 text-xs text-amber-700 hover:text-amber-950"
              >
                稍后继续
              </button>
            </div>
          )}
        </div>
      </div>

      <div className="border-t border-stone-200 bg-white px-6 py-4">
        <div className="max-w-[760px] mx-auto flex flex-col items-center gap-3">
          <button
            onClick={() => void onMicToggle()}
            disabled={micDisabled}
            aria-label={micPhase === 'recording' ? '结束录音' : '开始录音'}
            title={micPhase === 'recording' ? '点击结束录音' : '点击开始录音'}
            className={[
              'w-[88px] h-[88px] rounded-full flex flex-col items-center justify-center transition-all',
              micPhase === 'recording'
                ? 'bg-danger-500 text-white animate-pulse'
                : micPhase === 'preparing' || micPhase === 'requesting'
                ? 'bg-warning-500 text-white'
                : micDisabled
                ? 'bg-stone-100 text-stone-300 cursor-not-allowed'
                : 'bg-primary-500 text-white hover:bg-primary-600',
            ].join(' ')}
          >
            {micPhase === 'preparing' || micPhase === 'requesting' ? (
              <Loader2 size={28} className="animate-spin" />
            ) : micPhase === 'recording' ? (
              <Square size={28} />
            ) : (
              <Mic size={28} />
            )}
            <div className="text-[10px] mt-1">{micLabel}</div>
          </button>
          <div className="text-[10px] text-stone-400">
            录音结束后生成可编辑文字，确认无误再提交
          </div>
          {(voiceError || rec.errorMessage) && (
            <div className="w-full flex items-center gap-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2">
              <span className="flex-1 text-xs leading-5 text-amber-900">
                {voiceError || rec.errorMessage}
              </span>
              {voiceError && retryRecording && (
                <button
                  type="button"
                  onClick={() => void prepareRecording(retryRecording)}
                  className="shrink-0 text-xs font-medium text-amber-800 hover:text-amber-950"
                >
                  重试转写
                </button>
              )}
            </div>
          )}
          {voiceDraft && (
            <div className="w-full flex items-center gap-3 rounded-lg border border-primary-200 bg-primary-50 px-3 py-2">
              <span className="flex-1 text-xs leading-5 text-primary-800">
                已附带本次录音原声；你可以先修改转写文字，再提交回答。
              </span>
              <button
                type="button"
                onClick={() => setVoiceDraft(null)}
                className="shrink-0 text-xs text-primary-700 hover:text-primary-900"
              >
                改用纯文字
              </button>
            </div>
          )}
          <div className="w-full flex items-end gap-2">
            <textarea
              value={typing}
              onChange={(e) => setTyping(e.target.value)}
              rows={2}
              disabled={!canSubmit}
              placeholder="输入你的回答，Ctrl+Enter 提交"
              onKeyDown={(e) => {
                if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                  e.preventDefault();
                  void pushUserAnswer(typing, voiceDraft?.audioAssetId);
                }
              }}
              className="flex-1 resize-none border border-stone-200 rounded-md px-3 py-2 text-sm outline-none focus:border-primary-300 bg-stone-50 disabled:opacity-50"
            />
            <Btn
              size="md"
              icon={<CornerUpRight size={14} />}
              onClick={() => void pushUserAnswer(typing, voiceDraft?.audioAssetId)}
              disabled={!typing.trim() || !canSubmit}
              loading={operation === 'submitting' || operation === 'recovering'}
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
