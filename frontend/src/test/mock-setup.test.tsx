import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { MockSetup } from '@/pages/mock/MockSetup';
import { listResumes } from '@/api/resumes';

vi.mock('@/api/resumes', () => ({ listResumes: vi.fn(), createResumeFromFile: vi.fn(), waitForResumeUsable: vi.fn() }));
vi.mock('@/pages/career/JobOpportunitySelect', () => ({ JobOpportunitySelect: () => <span>岗位选择</span> }));
vi.mock('@/pages/mock/PreparationPanel', () => ({ PreparationPanel: () => <span>岗位证据</span> }));
beforeEach(() => { vi.clearAllMocks(); vi.mocked(listResumes).mockResolvedValue([]); localStorage.clear(); });

it('starts focused practice without resume/JD and preserves optional tuning when folded', async () => {
  const onReady = vi.fn();
  render(<MockSetup onReady={onReady} starting={false} />);
  await waitFor(() => expect(listResumes).toHaveBeenCalled());
  expect(screen.getByRole('button', { name: '请先完成必要设置' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: /专项练习/ }));
  fireEvent.change(screen.getByRole('textbox', { name: '本次考察目标' }), { target: { value: 'Python 协程取消和资源清理' } });
  fireEvent.click(screen.getByText('调整面试风格、题量与关联岗位'));
  fireEvent.click(screen.getByRole('button', { name: /严谨挑剔型/ }));
  fireEvent.click(screen.getByRole('button', { name: /快速面试/ }));
  fireEvent.click(screen.getByText('调整面试风格、题量与关联岗位'));
  fireEvent.click(screen.getByRole('button', { name: '开始模拟面试' }));
  expect(onReady).toHaveBeenCalledWith(expect.objectContaining({
    purpose: 'focused_practice', focus: 'Python 协程取消和资源清理',
    resume_id: undefined, jd_text: undefined, input_mode: 'text',
    interviewer_style: 'rigorous', target_question_count: 15,
  }));
});

it('changing back to a full interview requires its own inputs', async () => {
  render(<MockSetup onReady={vi.fn()} starting={false} />);
  fireEvent.click(screen.getByRole('button', { name: /专项练习/ }));
  fireEvent.change(screen.getByRole('textbox', { name: '本次考察目标' }), { target: { value: '数据库事务' } });
  await screen.findByRole('button', { name: '开始模拟面试' });
  fireEvent.click(screen.getByRole('button', { name: /完整模拟/ }));
  expect(screen.getByRole('button', { name: '请先完成必要设置' })).toBeDisabled();
});

it('confirms an existing Copilot handoff instead of starting a second request', async () => {
  const onReady = vi.fn(); const onPrefillApplied = vi.fn();
  render(<MockSetup onReady={onReady} starting={false} onPrefillApplied={onPrefillApplied}
    prefill={{ kind: 'mock_prefill', purpose: 'focused_practice', focus: '数据库事务', jd_text: '', interviewer_style: 'friendly', target_question_count: 15, input_mode: 'text' }} />);
  const confirm = screen.getByRole('button', { name: '确认设置并继续' });
  await waitFor(() => expect(confirm).toBeEnabled());
  fireEvent.click(confirm);
  expect(onPrefillApplied).toHaveBeenCalledWith({ outcome: 'acknowledged' });
  expect(onReady).not.toHaveBeenCalled();
});
