import { apiClient } from './client';
import type {
  MockClientAction,
  MockClientActionNotice,
  MockClientActionResolution,
  MockClientUiResult,
} from '@/types/clientAction';

export const CLIENT_ACTION_NOTICE_EVENT = 'interview-copilot:client-action';
export const CLIENT_ACTION_UI_RESULT_EVENT = 'interview-copilot:client-action-ui-result';

function actionPath(notice: MockClientActionNotice): string {
  const session = encodeURIComponent(notice.sessionId);
  const turn = encodeURIComponent(notice.turnId);
  const interaction = encodeURIComponent(notice.interactionId);
  return `/chat/${session}/turns/${turn}/client-actions/${interaction}`;
}

export function emitMockClientActionNotice(notice: MockClientActionNotice): void {
  window.dispatchEvent(new CustomEvent(CLIENT_ACTION_NOTICE_EVENT, { detail: notice }));
}

export function subscribeMockClientActions(
  listener: (notice: MockClientActionNotice) => void,
): () => void {
  const handler = (event: Event) => {
    listener((event as CustomEvent<MockClientActionNotice>).detail);
  };
  window.addEventListener(CLIENT_ACTION_NOTICE_EVENT, handler);
  return () => window.removeEventListener(CLIENT_ACTION_NOTICE_EVENT, handler);
}

export async function getPendingMockClientAction(
  notice: MockClientActionNotice,
  clientId: string,
): Promise<MockClientAction | null> {
  const response = await apiClient.get(
    `/chat/${encodeURIComponent(notice.sessionId)}/turns/${encodeURIComponent(notice.turnId)}/client-actions/pending`,
    { params: { client_id: clientId } },
  );
  return response.data as MockClientAction | null;
}

export async function takeoverMockClientAction(
  notice: MockClientActionNotice,
  clientId: string,
): Promise<MockClientAction> {
  const response = await apiClient.post(`${actionPath(notice)}/takeover`, {
    action_id: notice.actionId,
    expected_version: notice.version,
    client_id: clientId,
  });
  return response.data as MockClientAction;
}

export async function resolveMockClientAction(
  notice: MockClientActionNotice,
  action: MockClientAction,
  clientId: string,
  result: MockClientUiResult,
): Promise<MockClientActionResolution> {
  const response = await apiClient.post(`${actionPath(notice)}/resolve`, {
    action_id: action.action_id,
    client_id: clientId,
    expected_version: action.version,
    outcome: result.outcome,
    ...(result.readiness ? { readiness: result.readiness } : {}),
    ...(result.reason ? { reason: result.reason } : {}),
  });
  return response.data as MockClientActionResolution;
}

export function reportMockClientActionUiResult(
  actionId: string,
  result: MockClientUiResult,
): void {
  window.dispatchEvent(new CustomEvent(CLIENT_ACTION_UI_RESULT_EVENT, {
    detail: { actionId, result },
  }));
}

export function waitForMockClientActionUiResult(
  actionId: string,
  timeoutMs = 30_000,
): Promise<MockClientUiResult> {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (result: MockClientUiResult) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeoutId);
      window.removeEventListener(CLIENT_ACTION_UI_RESULT_EVENT, handler);
      resolve(result);
    };
    const handler = (event: Event) => {
      const detail = (event as CustomEvent<{
        actionId: string;
        result: MockClientUiResult;
      }>).detail;
      if (detail?.actionId === actionId) finish(detail.result);
    };
    const timeoutId = window.setTimeout(() => {
      finish({ outcome: 'failed', reason: '产品页面未能完成该客户端动作' });
    }, timeoutMs);
    window.addEventListener(CLIENT_ACTION_UI_RESULT_EVENT, handler);
  });
}
