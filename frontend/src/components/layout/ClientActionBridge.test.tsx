import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { MockClientAction, MockClientActionNotice } from '@/types/clientAction';

const mocks = vi.hoisted(() => ({
  getPending: vi.fn(),
  resolve: vi.fn(),
  subscribe: vi.fn(),
  takeover: vi.fn(),
  waitForUi: vi.fn(),
  getClientId: vi.fn(() => 'client-initiating'),
  navigate: vi.fn(),
}));

vi.mock('@/api/clientActions', () => ({
  getPendingMockClientAction: mocks.getPending,
  resolveMockClientAction: mocks.resolve,
  subscribeMockClientActions: mocks.subscribe,
  takeoverMockClientAction: mocks.takeover,
  waitForMockClientActionUiResult: mocks.waitForUi,
}));
vi.mock('@/api/chat', () => ({ getSourceClientId: mocks.getClientId }));
vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>();
  return { ...actual, useNavigate: () => mocks.navigate };
});

import { ClientActionBridge } from './ClientActionBridge';

const notice: MockClientActionNotice = {
  sessionId: 'session-1', turnId: 'turn-1', interactionId: 'interaction-1',
  version: 1, actionId: 'action-prefill', action: 'mock_interview.prefill',
};

function action(
  name: MockClientAction['action'],
  id: string,
  version: number,
): MockClientAction {
  const common = {
    interaction_id: `interaction-${version}`,
    turn_id: 'turn-1',
    tool_call_id: `tool-${version}`,
    version,
    action_id: id,
    action: name,
    takeover_generation: 0,
    created_at: '2026-08-13T00:00:00Z',
  };
  if (name === 'mock_interview.prefill') {
    return {
      ...common,
      action: name,
      payload: {
        kind: 'mock_prefill', resume_id: 'resume-1',
        jd_text: '这是一个长度足够的岗位说明，用于客户端动作测试。',
        interviewer_style: 'professional', target_question_count: 20,
      },
    };
  }
  if (name === 'mock_interview.check_readiness') {
    return { ...common, action: name, payload: { kind: 'mock_readiness', requirements: ['microphone'] } };
  }
  return {
    ...common,
    action: name,
    payload: {
      kind: 'mock_enter_live', record_id: 'record-1', conversation_id: 'mock-conversation-1',
      runtime_status: 'mock_in_progress',
    },
  };
}

let subscribed: ((value: MockClientActionNotice) => void) | null;

function emit(value = notice) {
  act(() => { subscribed?.(value); });
}

describe('ClientActionBridge', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
    subscribed = null;
    mocks.subscribe.mockImplementation((listener: (value: MockClientActionNotice) => void) => {
      subscribed = listener;
      return vi.fn();
    });
    mocks.resolve.mockResolvedValue({
      action_id: 'resolved', interaction_id: 'interaction', accepted: true, replayed: false,
      turn_status: 'waiting', dispatch_generation: 1,
    });
    mocks.waitForUi.mockResolvedValue({ outcome: 'acknowledged' });
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        getUserMedia: vi.fn().mockResolvedValue({
          getTracks: () => [{ stop: vi.fn() }],
        }),
      },
    });
  });

  it('lets the initiating client consume and resolve each retained phase in order', async () => {
    const prefill = action('mock_interview.prefill', 'action-prefill', 1);
    const readiness = action('mock_interview.check_readiness', 'action-readiness', 2);
    const enterLive = action('mock_interview.enter_live', 'action-live', 3);
    mocks.getPending
      .mockResolvedValueOnce(prefill)
      .mockResolvedValueOnce(readiness)
      .mockResolvedValueOnce(enterLive);
    render(<ClientActionBridge />);
    emit();

    await waitFor(() => expect(mocks.resolve).toHaveBeenCalledTimes(3));
    expect(mocks.getPending).toHaveBeenNthCalledWith(1, notice, 'client-initiating');
    expect(mocks.resolve.mock.calls.map((call) => call[1].action)).toEqual([
      'mock_interview.prefill',
      'mock_interview.check_readiness',
      'mock_interview.enter_live',
    ]);
    expect(mocks.resolve.mock.calls[1][3]).toEqual({
      outcome: 'acknowledged', readiness: 'ready',
    });
    expect(mocks.navigate).toHaveBeenCalledTimes(2);
  });

  it('does not consume a stranded action until the user explicitly takes it over', async () => {
    const enterLive = action('mock_interview.enter_live', 'action-live', 2);
    mocks.getPending.mockResolvedValueOnce(null);
    mocks.takeover.mockResolvedValue(enterLive);
    render(<ClientActionBridge />);
    emit();

    expect(await screen.findByText('模拟面试正在另一客户端等待')).toBeInTheDocument();
    expect(mocks.takeover).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: '在此继续' }));
    await waitFor(() => expect(mocks.takeover).toHaveBeenCalledWith(notice, 'client-initiating'));
    await waitFor(() => expect(mocks.resolve).toHaveBeenCalledWith(
      expect.objectContaining({ actionId: 'action-live' }),
      enterLive,
      'client-initiating',
      { outcome: 'acknowledged' },
    ));
  });

  it('reports a page guard refusal without navigating or claiming runtime success', async () => {
    const enterLive = action('mock_interview.enter_live', 'action-live', 2);
    mocks.getPending.mockResolvedValueOnce(enterLive);
    const guard = (event: Event) => event.preventDefault();
    window.addEventListener('interview-copilot:before-client-action', guard);
    render(<ClientActionBridge />);
    emit();

    await waitFor(() => expect(mocks.resolve).toHaveBeenCalledWith(
      expect.anything(), enterLive, 'client-initiating',
      { outcome: 'refused', reason: '当前页面有未保存内容，用户取消了跳转' },
    ));
    expect(mocks.navigate).not.toHaveBeenCalled();
    expect(mocks.waitForUi).not.toHaveBeenCalled();
    window.removeEventListener('interview-copilot:before-client-action', guard);
  });

  it('forwards a failed product-page result instead of fabricating runtime success', async () => {
    const enterLive = action('mock_interview.enter_live', 'action-live', 2);
    mocks.getPending.mockResolvedValueOnce(enterLive);
    mocks.waitForUi.mockResolvedValueOnce({
      outcome: 'failed', reason: '产品页面未确认 runtime 已进入 live',
    });
    render(<ClientActionBridge />);
    emit();

    await waitFor(() => expect(mocks.resolve).toHaveBeenCalledWith(
      expect.anything(), enterLive, 'client-initiating',
      { outcome: 'failed', reason: '产品页面未确认 runtime 已进入 live' },
    ));
  });

  it('replays a retained handoff after the bridge reconnects', async () => {
    const enterLive = action('mock_interview.enter_live', 'action-live', 2);
    const retained = { ...notice, interactionId: enterLive.interaction_id, actionId: enterLive.action_id, version: 2, action: enterLive.action };
    sessionStorage.setItem('mock-client-action-active-handoff-v1', JSON.stringify(retained));
    mocks.getPending.mockResolvedValueOnce(enterLive);
    render(<ClientActionBridge />);

    await waitFor(() => expect(mocks.getPending).toHaveBeenCalledWith(
      retained, 'client-initiating',
    ));
    await waitFor(() => expect(mocks.resolve).toHaveBeenCalledTimes(1));
    expect(sessionStorage.getItem('mock-client-action-active-handoff-v1')).toBeNull();
  });
});
