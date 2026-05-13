import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { MockSetup, type InterviewerStyle, type VoiceMode } from './MockSetup';
import { MockLive } from './MockLive';
import { toast } from '@/store/uiStore';
import { createChatSession } from '@/api/chat';
import {
  abandonMockInterview,
  getInProgressMock,
  getMockCurrentQuestion,
  startMockInterview,
} from '@/api/mock';
import type { MockQuestion } from '@/types/api';

type Stage =
  | { kind: 'setup' }
  | { kind: 'live'; sessionId: string; question: MockQuestion; voiceMode: VoiceMode };

interface InProgressBanner {
  sessionId: string;
  title: string;
  qaCount: number;
  lastActivityAt: string | null;
}

export function MockPage() {
  const [stage, setStage] = useState<Stage>({ kind: 'setup' });
  const [starting, setStarting] = useState(false);
  const [inProgress, setInProgress] = useState<InProgressBanner | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    if (stage.kind !== 'setup') return;
    let alive = true;
    getInProgressMock()
      .then((r) => {
        if (!alive || !r.has_in_progress || !r.session_id) return;
        setInProgress({
          sessionId: r.session_id,
          title: r.title ?? '模拟面试',
          qaCount: r.qa_count ?? 0,
          lastActivityAt: r.last_activity_at ?? null,
        });
      })
      .catch(() => {
        /* non-fatal */
      });
    return () => {
      alive = false;
    };
  }, [stage.kind]);

  const resumeInProgress = async () => {
    if (!inProgress) return;
    setStarting(true);
    try {
      const q = await getMockCurrentQuestion(inProgress.sessionId);
      setStage({
        kind: 'live',
        sessionId: inProgress.sessionId,
        question: q,
        voiceMode: 'hybrid',
      });
      setInProgress(null);
    } catch {
      toast.error('恢复面试失败');
    } finally {
      setStarting(false);
    }
  };

  const discardInProgress = async () => {
    if (!inProgress) return;
    try {
      await abandonMockInterview(inProgress.sessionId);
    } catch {
      /* non-fatal */
    }
    setInProgress(null);
  };

  const handleReady = async (payload: {
    resume_upload_id: string;
    jd_text: string;
    interviewer_style: InterviewerStyle;
    voice_mode: VoiceMode;
  }) => {
    setStarting(true);
    try {
      const session = await createChatSession({
        session_type: 'mock_interview',
        title: '模拟面试',
      });
      const started = await startMockInterview({
        session_id: session.session_id,
        resume_upload_id: payload.resume_upload_id,
        jd_text: payload.jd_text,
        interviewer_style: payload.interviewer_style,
        voice_mode: payload.voice_mode,
      });
      setStage({
        kind: 'live',
        sessionId: session.session_id,
        question: started.current_question,
        voiceMode: payload.voice_mode,
      });
    } catch {
      toast.error('启动模拟面试失败');
    } finally {
      setStarting(false);
    }
  };

  const onFinished = (recordId: string) => {
    toast.success('面试已结束，正在跳转到复盘');
    navigate(`/review?id=${encodeURIComponent(recordId)}`, { replace: true });
  };

  if (stage.kind === 'setup') {
    return (
      <>
        {inProgress && (
          <ResumeBanner
            banner={inProgress}
            onResume={resumeInProgress}
            onDiscard={discardInProgress}
            disabled={starting}
          />
        )}
        <MockSetup onReady={handleReady} starting={starting} />
      </>
    );
  }
  return (
    <MockLive
      sessionId={stage.sessionId}
      initialQuestion={stage.question}
      voiceMode={stage.voiceMode}
      onFinished={onFinished}
    />
  );
}

function ResumeBanner({
  banner,
  onResume,
  onDiscard,
  disabled,
}: {
  banner: InProgressBanner;
  onResume: () => void;
  onDiscard: () => void;
  disabled: boolean;
}) {
  const when = banner.lastActivityAt ? new Date(banner.lastActivityAt) : null;
  const whenLabel = when ? `${when.toLocaleString()}` : '不久前';
  return (
    <div className="max-w-[760px] mx-auto mt-6 px-4">
      <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 flex items-center gap-3">
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold text-amber-900">你有一个未完成的模拟面试</div>
          <div className="text-xs text-amber-800 mt-0.5">
            {banner.title} · 已答 {banner.qaCount} 题 · 最后活动 {whenLabel}
          </div>
        </div>
        <button
          type="button"
          onClick={onDiscard}
          disabled={disabled}
          className="text-xs text-stone-600 hover:text-stone-800 px-3 py-1.5 rounded border border-stone-200 bg-white"
        >
          放弃
        </button>
        <button
          type="button"
          onClick={onResume}
          disabled={disabled}
          className="text-xs text-white px-3 py-1.5 rounded bg-amber-600 hover:bg-amber-700 disabled:opacity-60"
        >
          继续
        </button>
      </div>
    </div>
  );
}
