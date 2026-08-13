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
