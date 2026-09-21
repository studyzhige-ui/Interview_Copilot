import { factInteraction } from '@/test/invitationFixtures';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { AgentInteraction } from '@/types/api';

const resolveAgentInteraction = vi.hoisted(() => vi.fn());
vi.mock('@/api/chat', () => ({ resolveAgentInteraction }));

import { InteractionCard } from './InteractionCard';

function renderCard(interaction: AgentInteraction) {
  const onResolved = vi.fn();
  render(<InteractionCard sessionId="session-1" turnId="turn-1" interaction={interaction} onResolved={onResolved} />);
  return onResolved;
}

const base = {
  id: 'interaction-1', turn_id: 'turn-1', tool_call_id: null,
  status: 'pending' as const, version: 1,
};

describe('InteractionCard typed resolutions', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resolveAgentInteraction.mockResolvedValue({ turn_status: 'pending' });
  });

  it('submits clarification text as an answer, not an approval decision', async () => {
    renderCard({ ...base, kind: 'clarification', request: { question: '你更看重哪个方向？' } });
    fireEvent.change(screen.getByLabelText('补充信息'), { target: { value: '平台工程' } });
    fireEvent.click(screen.getByRole('button', { name: '提交回答' }));
    await waitFor(() => expect(resolveAgentInteraction).toHaveBeenCalledWith(
      'session-1', 'turn-1', 'interaction-1',
      { expected_version: 1, status: 'resolved', resolution: { answer: '平台工程' } },
    ));
  });

  it('submits an approval only for an approval interaction', async () => {
    renderCard({ ...base, kind: 'approval', tool_call_id: 'call-1', request: { tool_name: 'send_email', arguments: { recipient: 'a@example.test' } } });
    fireEvent.click(screen.getByRole('button', { name: '批准本次操作' }));
    await waitFor(() => expect(resolveAgentInteraction).toHaveBeenCalledWith(
      'session-1', 'turn-1', 'interaction-1',
      { expected_version: 1, status: 'resolved', resolution: { decision: 'approved' } },
    ));
  });

  it('submits connection readiness with provider identity', async () => {
    renderCard({ ...base, kind: 'connection', tool_call_id: 'call-1', request: { tool_name: 'gmail_search_messages', reason: 'gmail_account_not_found' } });
    fireEvent.click(screen.getByRole('button', { name: '重新检查连接' }));
    await waitFor(() => expect(resolveAgentInteraction).toHaveBeenCalledWith(
      'session-1', 'turn-1', 'interaction-1',
      { expected_version: 1, status: 'resolved', resolution: { connection_status: 'ready', provider: 'gmail' } },
    ));
  });

  it('submits device readiness without granting a Tool approval', async () => {
    renderCard({ ...base, kind: 'client_readiness', request: { requirement: '允许麦克风后继续' } });
    fireEvent.click(screen.getByRole('button', { name: '已准备好' }));
    await waitFor(() => expect(resolveAgentInteraction).toHaveBeenCalledWith(
      'session-1', 'turn-1', 'interaction-1',
      { expected_version: 1, status: 'resolved', resolution: { ready: true } },
    ));
  });
});

describe('invitation fact confirmation, not generic approval', () => {
  beforeEach(() => { vi.clearAllMocks(); resolveAgentInteraction.mockResolvedValue({ turn_status: 'pending' }); });
  it('requires explicit opportunity selection and includes the exact CAS version', async () => {
    renderCard(factInteraction);
    expect(screen.queryByRole('button', { name: '批准本次操作' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '确认这些事实' })).toBeDisabled();
    fireEvent.change(screen.getByLabelText('关联求职机会'), { target: { value: 'job-1' } });
    fireEvent.click(screen.getByRole('button', { name: '确认这些事实' }));
    await waitFor(() => expect(resolveAgentInteraction).toHaveBeenCalledWith('session-1', 'turn-1', 'interaction-1',
      expect.objectContaining({ expected_version: 3, resolution_identity: expect.any(String), status: 'resolved',
        resolution: { protocol: 'interview_invitation.fact_confirmation.v1', decision: 'confirm',
          opportunity: { kind: 'link_existing', opportunity_id: 'job-1', expected_version: 2 } } })));
  });
  it('rejects an observation without sending canonical writes', async () => {
    renderCard(factInteraction); fireEvent.click(screen.getByRole('button', { name: '拒绝这条提取' }));
    await waitFor(() => expect(resolveAgentInteraction).toHaveBeenCalledWith('session-1', 'turn-1', 'interaction-1',
      expect.objectContaining({ status: 'rejected', resolution: { protocol: 'interview_invitation.fact_confirmation.v1', decision: 'reject' } })));
  });
  it('supports a corrected assertion and reuses its resolution identity after response loss', async () => {
    resolveAgentInteraction.mockRejectedValueOnce(new Error('offline'));
    renderCard(factInteraction); fireEvent.click(screen.getByRole('button', { name: '更正提取事实' }));
    fireEvent.change(screen.getByLabelText('公司'), { target: { value: '更正后的测试公司' } });
    fireEvent.change(screen.getByLabelText('关联求职机会'), { target: { value: 'new' } });
    fireEvent.click(screen.getByRole('button', { name: '更正并确认' }));
    // The existing error surface uses a toast; button becomes available for the same decision.
    await waitFor(() => expect(screen.getByRole('button', { name: '更正并确认' })).not.toBeDisabled());
    fireEvent.click(screen.getByRole('button', { name: '更正并确认' }));
    await waitFor(() => expect(resolveAgentInteraction).toHaveBeenCalledTimes(2));
    expect(resolveAgentInteraction.mock.calls[1][3]).toEqual(resolveAgentInteraction.mock.calls[0][3]);
    expect(resolveAgentInteraction.mock.calls[0][3].resolution.corrected_facts.company_name).toBe('更正后的测试公司');
  });
  it('fails closed for an unsupported schema version', () => {
    renderCard({ ...factInteraction, schema_version: 2 });
    expect(screen.getByRole('alert')).toHaveTextContent('暂不兼容');
    expect(resolveAgentInteraction).not.toHaveBeenCalled();
  });
});

it('requires complete correction when invitation time is missing or conflicting', () => {
  renderCard({ ...factInteraction, request: { ...factInteraction.request,
    missing_or_uncertain_fields: ['source_timezone'], conflicts: ['two possible start times'] } });
  expect(screen.getByRole('button', { name: '更正并确认' })).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('关联求职机会'), { target: { value: 'new' } });
  fireEvent.click(screen.getByRole('button', { name: '取消更正' }));
  expect(screen.getByRole('button', { name: '确认这些事实' })).toBeDisabled();
});
