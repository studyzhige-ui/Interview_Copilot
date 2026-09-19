import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { confirmInvitation, getInvitationSubmission, cancelInvitationSubmission, resumeInvitationSubmission } from '@/api/interviewInvitations';
import { useAuthStore } from '@/store/authStore';
import { confirmed, facts } from '@/test/invitationFixtures';
import { ManualInvitationForm, invitationStorageKey } from './ManualInvitationForm';
vi.mock('@/api/interviewInvitations', () => ({ confirmInvitation: vi.fn(), getInvitationSubmission: vi.fn(), cancelInvitationSubmission: vi.fn(), resumeInvitationSubmission: vi.fn() }));
function fill() {
  for (const [label, value] of [['公司', facts.company_name], ['岗位', facts.job_title],
    ['开始时间（含时区）', facts.scheduled_start_at], ['原始时间描述', facts.original_time_text], ['时间所属时区', facts.source_timezone]]) {
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
  }
}
describe('direct user assertion shares one Operation', () => {
  beforeEach(() => { vi.clearAllMocks(); sessionStorage.clear(); useAuthStore.setState({ subjectId: 'manual-owner', isAuthed: true }); vi.mocked(confirmInvitation).mockResolvedValue(confirmed); });
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
  it.each([403, 404, 422])('retains a previously unknown command after retry returns %s', async (status) => {
    vi.mocked(confirmInvitation).mockRejectedValueOnce(new Error('response lost'))
      .mockRejectedValueOnce({ isAxiosError: true, response: { status, data: { detail: 'retry rejected' } } });
    const done = vi.fn(); render(<ManualInvitationForm onConfirmed={done} />); fill();
    fireEvent.click(screen.getByRole('button', { name: '确认并保存面试' }));
    await screen.findByRole('alert');
    fireEvent.click(screen.getByRole('button', { name: '重试并核实原请求' }));
    await screen.findByText('retry rejected');
    expect(screen.getByLabelText('公司')).toBeDisabled();
    expect(done).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: '重试并核实原请求' }));
    await waitFor(() => expect(done).toHaveBeenCalledWith(confirmed));
    expect(confirmInvitation).toHaveBeenCalledTimes(3);
    expect(vi.mocked(confirmInvitation).mock.calls[2][0]).toEqual(vi.mocked(confirmInvitation).mock.calls[0][0]);
  });
  it('never declares success for an unknown verification', async () => {
    vi.mocked(confirmInvitation).mockResolvedValue({ ...confirmed, verification: { ...confirmed.verification, conclusion: 'unknown' } });
    const done = vi.fn(); render(<ManualInvitationForm onConfirmed={done} />); fill();
    fireEvent.click(screen.getByRole('button', { name: '确认并保存面试' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('尚未核实'); expect(done).not.toHaveBeenCalled();
  });
});


describe('reload reconciliation keeps only an opaque owner-scoped key', () => {
  beforeEach(() => { vi.clearAllMocks(); sessionStorage.clear(); useAuthStore.setState({ subjectId: 'reload-owner', isAuthed: true }); });
  it('recovers a committed receipt without replaying a POST', async () => {
    sessionStorage.setItem(invitationStorageKey('reload-owner'), 'manual-invitation:retained');
    vi.mocked(getInvitationSubmission).mockResolvedValue({ status: 'committed', idempotency_key: 'manual-invitation:retained', command: null, result: confirmed });
    const done = vi.fn(); render(<ManualInvitationForm onConfirmed={done} />);
    await waitFor(() => expect(done).toHaveBeenCalledWith(confirmed));
    expect(confirmInvitation).not.toHaveBeenCalled();
    expect(resumeInvitationSubmission).not.toHaveBeenCalled();
    expect(sessionStorage.getItem(invitationStorageKey('reload-owner'))).toBeNull();
  });
  it('retains a missing receipt and awaits an explicit cancellation tombstone', async () => {
    const key = 'manual-invitation:late';
    sessionStorage.setItem(invitationStorageKey('reload-owner'), key);
    vi.mocked(getInvitationSubmission).mockResolvedValue({ status: 'not_received', idempotency_key: key, command: null, result: null });
    vi.mocked(cancelInvitationSubmission).mockResolvedValue({ status: 'cancelled', idempotency_key: key, command: null, result: null });
    render(<ManualInvitationForm onConfirmed={vi.fn()} />);
    await screen.findByText(/暂未查到原请求/);
    expect(screen.getByLabelText('公司')).toBeDisabled();
    expect(sessionStorage.getItem(invitationStorageKey('reload-owner'))).toBe(key);
    fireEvent.click(screen.getByRole('button', { name: '取消原请求并重新填写' }));
    await waitFor(() => expect(screen.getByLabelText('公司')).not.toBeDisabled());
    expect(cancelInvitationSubmission).toHaveBeenCalledWith(key);
    expect(confirmInvitation).not.toHaveBeenCalled();
  });
  it('ignores a late receipt after the account component unmounts', async () => {
    sessionStorage.setItem(invitationStorageKey('reload-owner'), 'manual-invitation:old');
    let resolve!: (value: Awaited<ReturnType<typeof getInvitationSubmission>>) => void;
    vi.mocked(getInvitationSubmission).mockReturnValue(new Promise((r) => { resolve = r; }));
    const done = vi.fn(); const view = render(<ManualInvitationForm onConfirmed={done} />);
    view.unmount();
    resolve({ status: 'committed', idempotency_key: 'manual-invitation:old', command: null, result: confirmed });
    await Promise.resolve();
    expect(done).not.toHaveBeenCalled();
    expect(sessionStorage.getItem(invitationStorageKey('reload-owner'))).toBe('manual-invitation:old');
  });
  it('does not read another account identity retained identity', () => {
    sessionStorage.setItem(invitationStorageKey('another-owner'), 'manual-invitation:private');
    render(<ManualInvitationForm onConfirmed={vi.fn()} />);
    expect(getInvitationSubmission).not.toHaveBeenCalled();
  });
});
