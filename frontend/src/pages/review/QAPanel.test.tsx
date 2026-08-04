import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { editInterviewQA } from '@/api/interview';
import type { InterviewRecordDetail } from '@/types/api';
import { QAPanel } from './QAPanel';

vi.mock('@/api/interview', () => ({
  editInterviewQA: vi.fn(),
  saveQAToKnowledge: vi.fn(),
  unsaveQAFromKnowledge: vi.fn(),
}));

const detail: InterviewRecordDetail = {
  id: 'record-1',
  source: 'upload',
  title: '测试复盘',
  status: 'completed',
  created_at: '2026-08-03T10:00:00',
  updated_at: '2026-08-03T10:00:00',
  completed_at: '2026-08-03T10:00:00',
  analyzed_qa_count: 1,
  category: null,
  audio_file_asset_id: null,
  resume_id: null,
  resume_file_asset_id: null,
  resume_source: null,
  jd_file_asset_id: null,
  transcript: null,
  transcript_segments: null,
  interview_plan: null,
  analysis: null,
  error_message: null,
  qa: [
    {
      id: 'qa-1',
      order_idx: 0,
      phase: 'technical',
      question: '原问题',
      answer: '原答案',
      is_follow_up: false,
      follow_up_depth: 0,
      grounding_refs: [],
      key_points: [],
      answer_input_mode: 'text',
    },
  ],
};

describe('QAPanel editing', () => {
  beforeEach(() => {
    vi.mocked(editInterviewQA).mockReset().mockResolvedValue(undefined);
  });

  it('persists a value changed back to the original after an earlier save', async () => {
    render(<QAPanel detail={detail} loading={false} />);
    fireEvent.click(screen.getByRole('button', { name: 'QA 对' }));

    fireEvent.doubleClick(screen.getByText('原问题'));
    fireEvent.change(screen.getByDisplayValue('原问题'), { target: { value: '新问题' } });
    fireEvent.blur(screen.getByDisplayValue('新问题'));

    await waitFor(() => {
      expect(editInterviewQA).toHaveBeenCalledWith('record-1', 'qa-1', {
        question: '新问题',
      });
    });

    fireEvent.doubleClick(screen.getByText('新问题'));
    fireEvent.change(screen.getByDisplayValue('新问题'), { target: { value: '原问题' } });
    fireEvent.blur(screen.getByDisplayValue('原问题'));

    await waitFor(() => {
      expect(editInterviewQA).toHaveBeenNthCalledWith(2, 'record-1', 'qa-1', {
        question: '原问题',
      });
    });
  });
});
