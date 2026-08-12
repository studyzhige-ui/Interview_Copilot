import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  loadPreferredVoice,
  MockSetup,
  type InterviewerStyle,
  type TargetQuestionCount,
  type TtsVoice,
} from './MockSetup';
import { MockLive } from './MockLive';
import { toast } from '@/store/uiStore';
import type { MockLiveMessage } from '@/types/api';
import {
  abandonMockInterview,
  getInProgressMock,
  startMockInterview,
} from '@/api/mock';

type Stage =
  | { kind: 'setup' }
  | {
      kind: 'live';
      recordId: string;
      initialMessages?: MockLiveMessage[];
      ttsVoice: TtsVoice;
    };

interface InProgressBanner {
  recordId: string;
  title: string;
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
        if (!alive || !r.has_in_progress || !r.record_id) return;
        setInProgress({
          recordId: r.record_id,
          title: r.title ?? '模拟面试',
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

  const resumeInProgress = () => {
    if (!inProgress) return;
    setStage({
      kind: 'live',
      recordId: inProgress.recordId,
      ttsVoice: loadPreferredVoice(),
    });
    setInProgress(null);
  };

  const discardInProgress = async () => {
    if (!inProgress) return;
    try {
      await abandonMockInterview(inProgress.recordId);
    } catch {
      /* non-fatal */
    }
    setInProgress(null);
  };

  const handleReady = async (payload: {
    resume_id: string;
    jd_text: string;
    interviewer_style: InterviewerStyle;
    tts_voice: TtsVoice;
    target_question_count: TargetQuestionCount;
  }) => {
    setStarting(true);
    try {
      const started = await startMockInterview({
        resume_id: payload.resume_id,
        jd_text: payload.jd_text,
        interviewer_style: payload.interviewer_style,
        target_question_count: payload.target_question_count,
      });
      setStage({
        kind: 'live',
        recordId: started.record_id,
        initialMessages: [started.message],
        ttsVoice: payload.tts_voice,
      });
    } catch {
      toast.error('启动模拟面试失败');
    } finally {
      setStarting(false);
    }
  };

  const onFinished = (recordId: string) => {
    toast.success('面试已结束，正在跳转到复盘');
    setStage({ kind: 'setup' });
    navigate(`/review?id=${encodeURIComponent(recordId)}`, { replace: true });
  };

  // Abandon: hard-delete on backend + reset local stage so MockSetup remounts
  // fresh. The MockLive child also navigate('/mock'), but the stage reset is
  // what actually makes the setup page show.
  const onAbandoned = () => {
    setStage({ kind: 'setup' });
    setInProgress(null);
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
      recordId={stage.recordId}
      initialMessages={stage.initialMessages}
      ttsVoice={stage.ttsVoice}
      onFinished={onFinished}
      onAbandoned={onAbandoned}
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
            {banner.title} · 最后活动 {whenLabel}
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
