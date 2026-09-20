import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { editInterviewQA, getInterviewRecord } from '@/api/interview';
import type { InterviewQA, InterviewRecordDetail } from '@/types/api';
import { QAEditor } from './QAEditor';
vi.mock('@/api/interview', () => ({ editInterviewQA: vi.fn(), getInterviewRecord: vi.fn() }));
const qa: InterviewQA = {
  id: 'q1', version: 1, order_idx: 0, phase: 'technical', question: '原问题', answer: '原答案',
  is_follow_up: false, follow_up_depth: 0, grounding_refs: [], key_points: [], answer_input_mode: 'text',
};
const detail = (saved: InterviewQA) => ({ id: 'r1', qa: [saved] } as InterviewRecordDetail);
const edit = () => {
  fireEvent.change(screen.getByRole('textbox', { name: '回答草稿' }), { target: { value: '我的修改' } });
  fireEvent.blur(screen.getByRole('textbox', { name: '回答草稿' }));
};
beforeEach(() => vi.resetAllMocks());
describe('versioned QA correction', () => {
  it('writes only on explicit save and sends both visible fields atomically', async () => {
    const saved = vi.fn();
    vi.mocked(editInterviewQA).mockResolvedValue({ ...qa, answer: '我的修改', version: 2 });
    render(<QAEditor recordId="r1" qa={qa} onSaved={saved} onClose={vi.fn()} />);
    edit();
    expect(editInterviewQA).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: '保存修改' }));
    await waitFor(() => expect(saved).toHaveBeenCalledOnce());
    expect(editInterviewQA).toHaveBeenCalledWith('r1', 'q1', {
      expected_version: 1, question: '原问题', answer: '我的修改',
    });
  });
  it('reconciles a lost success response by reading without another write', async () => {
    const saved = vi.fn();
    vi.mocked(editInterviewQA).mockRejectedValue(new Error('lost response'));
    vi.mocked(getInterviewRecord).mockResolvedValue(detail({ ...qa, answer: '我的修改', version: 2 }));
    render(<QAEditor recordId="r1" qa={qa} onSaved={saved} onClose={vi.fn()} />);
    edit();
    fireEvent.click(screen.getByRole('button', { name: '保存修改' }));
    await screen.findByRole('alert');
    expect(screen.getByDisplayValue('我的修改')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '核对保存状态' }));
    await waitFor(() => expect(saved).toHaveBeenCalledOnce());
    expect(editInterviewQA).toHaveBeenCalledTimes(1);
  });
  it('shows a conflicting server version, preserves the draft and requires consent', async () => {
    const saved = vi.fn();
    vi.mocked(editInterviewQA).mockRejectedValueOnce({ response: { status: 409 } })
      .mockResolvedValueOnce({ ...qa, answer: '我的修改', version: 4 });
    vi.mocked(getInterviewRecord).mockResolvedValue(detail({ ...qa, answer: '其他窗口的修改', version: 3 }));
    render(<QAEditor recordId="r1" qa={qa} onSaved={saved} onClose={vi.fn()} />);
    edit();
    fireEvent.click(screen.getByRole('button', { name: '保存修改' }));
    await screen.findByRole('alert');
    fireEvent.click(screen.getByRole('button', { name: '核对保存状态' }));
    await screen.findByText('服务器版本 3');
    expect(screen.getByText('回答：其他窗口的修改')).toBeInTheDocument();
    expect(screen.getByDisplayValue('我的修改')).toBeInTheDocument();
    expect(editInterviewQA).toHaveBeenCalledTimes(1);
    expect(saved).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: '以服务器当前版本保存我的修改' }));
    await waitFor(() => expect(saved).toHaveBeenCalledOnce());
    expect(editInterviewQA).toHaveBeenLastCalledWith('r1', 'q1', {
      expected_version: 3, question: '原问题', answer: '我的修改',
    });
  });
  it('does not update the parent after the editor unmounts', async () => {
    let resolve!: (value: InterviewQA) => void;
    vi.mocked(editInterviewQA).mockReturnValue(new Promise((res) => { resolve = res; }));
    const saved = vi.fn();
    const { unmount } = render(<QAEditor recordId="r1" qa={qa} onSaved={saved} onClose={vi.fn()} />);
    edit(); fireEvent.click(screen.getByRole('button', { name: '保存修改' }));
    unmount(); resolve({ ...qa, answer: '我的修改', version: 2 });
    await Promise.resolve(); await Promise.resolve();
    expect(saved).not.toHaveBeenCalled();
  });
});
