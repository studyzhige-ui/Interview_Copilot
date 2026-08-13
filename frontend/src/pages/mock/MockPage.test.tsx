import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  abandonMockInterview: vi.fn(),
  getInProgressMock: vi.fn(),
  startMockInterview: vi.fn(),
  reportMockClientActionUiResult: vi.fn(),
}));

vi.mock('@/api/mock', () => ({
  abandonMockInterview: api.abandonMockInterview,
  getInProgressMock: api.getInProgressMock,
  startMockInterview: api.startMockInterview,
}));
vi.mock('@/api/clientActions', () => ({
  reportMockClientActionUiResult: api.reportMockClientActionUiResult,
}));
vi.mock('./MockSetup', () => ({
  loadPreferredVoice: () => 'zh-CN-YunxiNeural',
  MockSetup: ({ onReady }: { onReady: (payload: Record<string, unknown>) => void }) => (
    <button type="button" onClick={() => onReady({
      resume_id: 'resume-1',
      jd_text: '这是一个长度足够的岗位说明，用于模拟面试测试。',
      interviewer_style: 'professional',
      tts_voice: 'zh-CN-YunxiNeural',
      target_question_count: 20,
      job_opportunity_id: 'job-1',
    })}>
      开始测试模拟面试
    </button>
  ),
}));
vi.mock('./MockLive', () => ({
  MockLive: ({ recordId }: { recordId: string }) => <div>Live {recordId}</div>,
}));

import { MockPage } from './MockPage';

describe('MockPage JobOpportunity handoff', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getInProgressMock.mockResolvedValue({ has_in_progress: false });
    api.startMockInterview.mockResolvedValue({
      record_id: 'record-1',
      message: { id: 1, speaker: 'interviewer', text: '你好' },
    });
  });

  it('preserves the selected JobOpportunity through the final start command', async () => {
    render(<MemoryRouter><MockPage /></MemoryRouter>);
    fireEvent.click(screen.getByRole('button', { name: '开始测试模拟面试' }));
    await waitFor(() => expect(api.startMockInterview).toHaveBeenCalledWith({
      resume_id: 'resume-1',
      jd_text: '这是一个长度足够的岗位说明，用于模拟面试测试。',
      interviewer_style: 'professional',
      target_question_count: 20,
      job_opportunity_id: 'job-1',
    }));
    expect(await screen.findByText('Live record-1')).toBeInTheDocument();
  });
});
