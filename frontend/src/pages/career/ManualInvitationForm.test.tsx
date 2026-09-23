import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { ManualInvitationForm } from './ManualInvitationForm';
import { apiClient } from '@/api/client';

vi.mock('@/api/client', () => ({ apiClient: { post: vi.fn() }, extractErr: () => '连接中断，请重试' }));
beforeEach(() => vi.clearAllMocks());

it('preserves the same verified operation on a retry after an uncertain response', async () => {
  const saved = vi.fn();
  vi.mocked(apiClient.post).mockRejectedValueOnce(new Error('network')).mockResolvedValueOnce({ data: { replayed: true } });
  render(<ManualInvitationForm onSaved={saved} />);
  fireEvent.change(screen.getByLabelText('公司'), { target: { value: '示例科技' } });
  fireEvent.change(screen.getByLabelText('岗位'), { target: { value: '后端工程师' } });
  fireEvent.change(screen.getByLabelText('面试时间（本地时区）'), { target: { value: '2026-10-01T10:00' } });
  fireEvent.click(screen.getByRole('button', { name: '保存面试安排' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('连接中断');
  expect(saved).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: '保存面试安排' }));
  await waitFor(() => expect(saved).toHaveBeenCalledOnce());
  expect(vi.mocked(apiClient.post).mock.calls[0]).toEqual(vi.mocked(apiClient.post).mock.calls[1]);
  expect(vi.mocked(apiClient.post).mock.calls[0][1]).toMatchObject({ actor_kind: 'user', opportunity: { kind: 'create_new' }, confirmation_basis: { kind: 'explicit_user_assertion' } });
});
