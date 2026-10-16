import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, expect, it, vi } from 'vitest';
import { ManualInvitationForm } from '@/pages/career/ManualInvitationForm';
import { confirmInvitation, getInvitationSubmission, resumeInvitationSubmission, cancelInvitationSubmission, type InvitationSubmissionReceipt } from '@/api/interviewInvitations';

vi.mock('@/api/interviewInvitations', () => ({ confirmInvitation: vi.fn(), getInvitationSubmission: vi.fn(), resumeInvitationSubmission: vi.fn(), cancelInvitationSubmission: vi.fn() }));
vi.mock('@/store/authStore', () => ({ useAuthStore: (select: (value: { subjectId: string }) => unknown) => select({ subjectId: 'test-owner' }) }));
vi.mock('@/pages/career/useCareerWorkspace', () => ({ useRefreshCareer: () => async () => {} }));
const cache = 'invitation-submission:test-owner:new:new';
const receipt = (status: InvitationSubmissionReceipt['status']): InvitationSubmissionReceipt => ({ status, idempotency_key: 'durable-key', command: null, result: null });
beforeEach(() => { vi.clearAllMocks(); localStorage.clear(); });
function show(onSaved = vi.fn()) {
  return { onSaved, ...render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><ManualInvitationForm onSaved={onSaved} /></QueryClientProvider>) };
}

it('recovers a pending server command after remount without recreating it', async () => {
  localStorage.setItem(cache, 'durable-key');
  vi.mocked(getInvitationSubmission).mockResolvedValue(receipt('pending'));
  const { onSaved } = show();
  fireEvent.click(await screen.findByRole('button', { name: '继续上次保存' }));
  await waitFor(() => expect(onSaved).toHaveBeenCalledOnce());
  expect(resumeInvitationSubmission).toHaveBeenCalledWith('durable-key');
  expect(confirmInvitation).not.toHaveBeenCalled();
  expect(localStorage.getItem(cache)).toBeNull();
});

it('recognizes a committed result after a lost response without replaying a write', async () => {
  localStorage.setItem(cache, 'durable-key');
  vi.mocked(getInvitationSubmission).mockResolvedValue(receipt('committed'));
  const { onSaved } = show();
  fireEvent.click(await screen.findByRole('button', { name: '查看已保存安排' }));
  expect(onSaved).toHaveBeenCalledOnce();
  expect(confirmInvitation).not.toHaveBeenCalled();
  expect(resumeInvitationSubmission).not.toHaveBeenCalled();
});

it('keeps a missing command locked until server cancellation prevents a delayed write', async () => {
  localStorage.setItem(cache, 'durable-key');
  vi.mocked(getInvitationSubmission).mockResolvedValue(receipt('not_received'));
  let release!: (value: InvitationSubmissionReceipt) => void;
  vi.mocked(cancelInvitationSubmission).mockReturnValue(new Promise(resolve => { release = resolve; }));
  show();
  fireEvent.click(await screen.findByRole('button', { name: '取消未完成保存' }));
  expect(screen.getByLabelText('公司')).toBeDisabled();
  expect(localStorage.getItem(cache)).toBe('durable-key');
  release(receipt('cancelled'));
  await waitFor(() => expect(screen.getByLabelText('公司')).toBeEnabled());
  expect(localStorage.getItem(cache)).toBeNull();
});

it('retains the opaque recovery key when saving loses its response', async () => {
  vi.mocked(getInvitationSubmission).mockResolvedValue(receipt('pending'));
  vi.mocked(confirmInvitation).mockRejectedValue(new Error('network interrupted'));
  const { unmount } = show();
  fireEvent.change(screen.getByLabelText('公司'), { target: { value: '恢复测试公司' } });
  fireEvent.change(screen.getByLabelText('岗位'), { target: { value: '工程师' } });
  fireEvent.change(screen.getByLabelText('面试时间（本地时区）'), { target: { value: '2030-11-01T12:00' } });
  fireEvent.click(screen.getByRole('button', { name: '保存面试安排' }));
  await screen.findByText('network interrupted');
  const command = vi.mocked(confirmInvitation).mock.calls[0][0];
  expect(localStorage.getItem(cache)).toBe(command.idempotency_key);
  expect(localStorage.getItem(cache)).not.toContain('恢复测试公司');
  unmount(); sessionStorage.clear(); show();
  await screen.findByRole('button', { name: '继续上次保存' });
  expect(confirmInvitation).toHaveBeenCalledOnce();
});
