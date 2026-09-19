import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getInvitationHandoff, listInvitationHandoffs } from '@/api/interviewInvitations';
import { reportMockClientActionUiResult } from '@/api/clientActions';
import { handoff } from '@/test/invitationFixtures';
import { InterviewHubPage } from './InterviewHubPage';
vi.mock('@/api/interviewInvitations', () => ({ getInvitationHandoff: vi.fn(), listInvitationHandoffs: vi.fn(), confirmInvitation: vi.fn() }));
vi.mock('@/api/clientActions', () => ({ reportMockClientActionUiResult: vi.fn() }));
function mount() {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter initialEntries={[{ pathname: '/interviews', state: { mockClientAction: {
      action: 'interview.preparation.open', action_id: 'action-1', payload: { kind: 'interview_preparation_open',
        interview_id: 'interview-1', opportunity_id: 'job-1', expected_interview_version: 1,
        expected_opportunity_version: 2, source_operation_id: 'operation-1', preferred_surface: 'interviews' } } } }]}>
      <InterviewHubPage />
    </MemoryRouter></QueryClientProvider>);
}
describe('verified preparation handoff', () => {
  beforeEach(() => { vi.clearAllMocks(); vi.mocked(listInvitationHandoffs).mockResolvedValue([]); vi.mocked(getInvitationHandoff).mockResolvedValue(handoff); });
  it('acknowledges only after reading the exact owned versions and operation receipt', async () => {
    mount(); expect(await screen.findByText('测试公司 · 测试工程师')).toBeInTheDocument();
    await waitFor(() => expect(reportMockClientActionUiResult).toHaveBeenCalledWith('action-1', { outcome: 'acknowledged' }));
    expect(reportMockClientActionUiResult).toHaveBeenCalledTimes(1);
  });
  it.each(['stale', 'unknown', 'different-operation', 'forbidden'])('refuses %s handoff without fabricating success', async (kind) => {
    if (kind === 'forbidden') vi.mocked(getInvitationHandoff).mockRejectedValue(new Error('404'));
    else vi.mocked(getInvitationHandoff).mockResolvedValue({ ...handoff,
      interview: kind === 'stale' ? { ...handoff.interview, version: 2 } : handoff.interview,
      verification: { ...handoff.verification, conclusion: kind === 'unknown' ? 'unknown' : 'verified',
        operation_id: kind === 'different-operation' ? 'other-operation' : 'operation-1' } });
    mount(); await waitFor(() => expect(reportMockClientActionUiResult).toHaveBeenCalledWith('action-1', expect.objectContaining({ outcome: 'failed' })));
    expect(reportMockClientActionUiResult).not.toHaveBeenCalledWith('action-1', { outcome: 'acknowledged' });
  });
});
