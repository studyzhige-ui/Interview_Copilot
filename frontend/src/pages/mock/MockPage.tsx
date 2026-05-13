import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { MockSetup } from './MockSetup';
import { MockLive } from './MockLive';
import { toast } from '@/store/uiStore';
import { createChatSession } from '@/api/chat';
import { startMockInterview } from '@/api/mock';
import type { MockQuestion } from '@/types/api';

type Stage =
  | { kind: 'setup' }
  | { kind: 'live'; sessionId: string; question: MockQuestion };

export function MockPage() {
  const [stage, setStage] = useState<Stage>({ kind: 'setup' });
  const [starting, setStarting] = useState(false);
  const navigate = useNavigate();

  const handleReady = async (payload: { resume_upload_id: string; jd_doc_id: string }) => {
    setStarting(true);
    try {
      const session = await createChatSession({
        session_type: 'mock_interview',
        title: '模拟面试',
      });
      const started = await startMockInterview({
        session_id: session.session_id,
        resume_upload_id: payload.resume_upload_id,
        jd_upload_id: payload.jd_doc_id,
      });
      setStage({
        kind: 'live',
        sessionId: session.session_id,
        question: started.current_question,
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
    return <MockSetup onReady={handleReady} starting={starting} />;
  }
  return (
    <MockLive
      sessionId={stage.sessionId}
      initialQuestion={stage.question}
      onFinished={onFinished}
    />
  );
}
