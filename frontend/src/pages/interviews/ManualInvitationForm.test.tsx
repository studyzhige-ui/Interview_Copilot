import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { confirmInvitation } from '@/api/interviewInvitations';
import { confirmed, facts } from '@/test/invitationFixtures';
import { ManualInvitationForm } from './ManualInvitationForm';
vi.mock('@/api/interviewInvitations', () => ({ confirmInvitation: vi.fn() }));
function fill() {
  for (const [label, value] of [['公司', facts.company_name], ['岗位', facts.job_title],
    ['开始时间（含时区）', facts.scheduled_start_at], ['原始时间描述', facts.original_time_text], ['时间所属时区', facts.source_timezone]]) {
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
  }
}
describe('direct user assertion shares one Operation', () => {
  beforeEach(() => { vi.clearAllMocks(); vi.mocked(confirmInvitation).mockResolvedValue(confirmed); });
  it('does not write on mount and sends exactly one explicit fact command', async () => {
    const onConfirmed = vi.fn(); render(<ManualInvitationForm onConfirmed={onConfirmed} />); fill();
    expect(confirmInvitation).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: '确认并保存面试' }));
    await waitFor(() => expect(onConfirmed).toHaveBeenCalledWith(confirmed));
    expect(confirmInvitation).toHaveBeenCalledTimes(1);
    expect(vi.mocked(confirmInvitation).mock.calls[0][0]).toMatchObject({ actor_kind: 'user', facts,
      confirmation_basis: { kind: 'explicit_user_assertion', source: { kind: 'manual' } }, opportunity: { kind: 'create_new' } });
  });
  it('retries unchanged assertion time, fields and idempotency key after response loss', async () => {
    vi.mocked(confirmInvitation).mockRejectedValueOnce(new Error('response lost'));
    render(<ManualInvitationForm onConfirmed={vi.fn()} />); fill();
    fireEvent.click(screen.getByRole('button', { name: '确认并保存面试' }));
    await screen.findByRole('alert'); expect(screen.getByLabelText('公司')).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: '重试并核实原请求' }));
    await waitFor(() => expect(confirmInvitation).toHaveBeenCalledTimes(2));
    expect(vi.mocked(confirmInvitation).mock.calls[1][0]).toEqual(vi.mocked(confirmInvitation).mock.calls[0][0]);
  });
  it('allows correction after a definite validation rejection', async () => {
    vi.mocked(confirmInvitation).mockRejectedValueOnce({ isAxiosError: true, response: { status: 422, data: { detail: 'invalid facts' } } });
    render(<ManualInvitationForm onConfirmed={vi.fn()} />); fill();
    fireEvent.click(screen.getByRole('button', { name: '确认并保存面试' }));
    await screen.findByRole('alert');
    expect(screen.getByLabelText('公司')).not.toBeDisabled();
    fireEvent.change(screen.getByLabelText('公司'), { target: { value: 'Corrected company' } });
    fireEvent.click(screen.getByRole('button', { name: '确认并保存面试' }));
    await waitFor(() => expect(confirmInvitation).toHaveBeenCalledTimes(2));
    expect(vi.mocked(confirmInvitation).mock.calls[1][0].facts.company_name).toBe('Corrected company');
    expect(vi.mocked(confirmInvitation).mock.calls[1][0].idempotency_key).not.toBe(vi.mocked(confirmInvitation).mock.calls[0][0].idempotency_key);
  });
  it('never declares success for an unknown verification', async () => {
    vi.mocked(confirmInvitation).mockResolvedValue({ ...confirmed, verification: { ...confirmed.verification, conclusion: 'unknown' } });
    const done = vi.fn(); render(<ManualInvitationForm onConfirmed={done} />); fill();
    fireEvent.click(screen.getByRole('button', { name: '确认并保存面试' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('尚未核实'); expect(done).not.toHaveBeenCalled();
  });
});
