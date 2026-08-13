import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  getPendingMockClientAction,
  resolveMockClientAction,
  subscribeMockClientActions,
  takeoverMockClientAction,
  waitForMockClientActionUiResult,
} from '@/api/clientActions';
import { getSourceClientId } from '@/api/chat';
import { toast } from '@/store/uiStore';
import type {
  MockClientAction,
  MockClientActionNotice,
  MockClientUiResult,
  MockRouteActionState,
} from '@/types/clientAction';

const ACTIVE_HANDOFF_KEY = 'mock-client-action-active-handoff-v1';

function saveActiveHandoff(notice: MockClientActionNotice | null): void {
  try {
    if (notice) sessionStorage.setItem(ACTIVE_HANDOFF_KEY, JSON.stringify(notice));
    else sessionStorage.removeItem(ACTIVE_HANDOFF_KEY);
  } catch {
    // The server remains authoritative when browser storage is unavailable.
  }
}

function loadActiveHandoff(): MockClientActionNotice | null {
  try {
    const raw = sessionStorage.getItem(ACTIVE_HANDOFF_KEY);
    return raw ? JSON.parse(raw) as MockClientActionNotice : null;
  } catch {
    return null;
  }
}

function noticeForAction(
  base: MockClientActionNotice,
  action: MockClientAction,
): MockClientActionNotice {
  return {
    sessionId: base.sessionId,
    turnId: base.turnId,
    interactionId: action.interaction_id,
    version: action.version,
    actionId: action.action_id,
    action: action.action,
  };
}

function clientGuardAllows(action: MockClientAction): boolean {
  const guard = new CustomEvent('interview-copilot:before-client-action', {
    cancelable: true,
    detail: { action: action.action, actionId: action.action_id },
  });
  return window.dispatchEvent(guard);
}

async function microphoneReadiness(): Promise<MockClientUiResult> {
  if (!navigator.mediaDevices?.getUserMedia) {
    return { outcome: 'failed', reason: '当前客户端不支持麦克风权限检查' };
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    stream.getTracks().forEach((track) => track.stop());
    return { outcome: 'acknowledged', readiness: 'ready' };
  } catch (error) {
    const name = error instanceof DOMException ? error.name : '';
    return {
      outcome: name === 'NotAllowedError' ? 'refused' : 'failed',
      reason: name === 'NotAllowedError' ? '用户未授予麦克风权限' : '麦克风当前不可用',
    };
  }
}

/** Stable AppShell consumer for the one fixed Mock Client Action contract. */
export function ClientActionBridge() {
  const navigate = useNavigate();
  const processing = useRef(new Set<string>());
  const [stranded, setStranded] = useState<MockClientActionNotice | null>(null);

  const pollNext = useCallback(async (notice: MockClientActionNotice) => {
    saveActiveHandoff(notice);
    for (let attempt = 0; attempt < 120; attempt += 1) {
      const pending = await getPendingMockClientAction(notice, getSourceClientId());
      if (pending) return pending;
      await new Promise((resolve) => window.setTimeout(resolve, 500));
    }
    return null;
  }, []);

  const run = useCallback(async (
    notice: MockClientActionNotice,
    initialAction: MockClientAction,
  ) => {
    let action: MockClientAction | null = initialAction;
    let baseNotice = notice;
    while (action) {
      if (processing.current.has(action.action_id)) return;
      processing.current.add(action.action_id);
      const processingActionId = action.action_id;
      const effectiveNotice = noticeForAction(baseNotice, action);
      saveActiveHandoff(effectiveNotice);
      try {
        let result: MockClientUiResult;
        if (action.action === 'mock_interview.check_readiness') {
          result = await microphoneReadiness();
        } else if (!clientGuardAllows(action)) {
          result = { outcome: 'refused', reason: '当前页面有未保存内容，用户取消了跳转' };
        } else {
          navigate('/mock', {
            state: { mockClientAction: action } satisfies MockRouteActionState,
          });
          result = await waitForMockClientActionUiResult(action.action_id);
        }
        await resolveMockClientAction(
          effectiveNotice,
          action,
          getSourceClientId(),
          result,
        );
        if (action.action === 'mock_interview.enter_live') {
          saveActiveHandoff(null);
          return;
        }
        baseNotice = effectiveNotice;
        action = await pollNext(effectiveNotice);
      } catch {
        toast.error('客户端动作未能完成，可返回原对话重试');
        return;
      } finally {
        processing.current.delete(processingActionId);
      }
    }
  }, [navigate, pollNext]);

  const receive = useCallback(async (notice: MockClientActionNotice) => {
    saveActiveHandoff(notice);
    try {
      const action = await getPendingMockClientAction(notice, getSourceClientId());
      if (action) {
        setStranded(null);
        await run(notice, action);
      } else {
        // Other tabs may observe Turn status, but they cannot consume the
        // payload until the user explicitly chooses takeover.
        setStranded(notice);
      }
    } catch {
      // A stale/terminal action needs no client effect.
    }
  }, [run]);

  useEffect(() => {
    const unsubscribe = subscribeMockClientActions((notice) => { void receive(notice); });
    const retained = loadActiveHandoff();
    const timerId = retained
      ? window.setTimeout(() => { void receive(retained); }, 0)
      : undefined;
    return () => {
      unsubscribe();
      if (timerId !== undefined) window.clearTimeout(timerId);
    };
  }, [receive]);

  const takeover = async () => {
    if (!stranded) return;
    try {
      const action = await takeoverMockClientAction(stranded, getSourceClientId());
      setStranded(null);
      await run(stranded, action);
    } catch {
      toast.error('该客户端动作已被处理或已发生变化');
      setStranded(null);
    }
  };

  if (!stranded) return null;
  return (
    <div className="fixed bottom-5 right-5 z-50 max-w-sm rounded-xl border border-amber-200 bg-white p-4 shadow-xl">
      <p className="text-sm font-semibold text-stone-800">模拟面试正在另一客户端等待</p>
      <p className="mt-1 text-xs leading-relaxed text-stone-500">
        只有你明确接管后，本标签页才会收到并执行页面动作。
      </p>
      <div className="mt-3 flex justify-end gap-2">
        <button
          type="button"
          className="rounded-md px-3 py-1.5 text-xs text-stone-600 hover:bg-stone-100"
          onClick={() => setStranded(null)}
        >
          暂不处理
        </button>
        <button
          type="button"
          className="rounded-md bg-amber-600 px-3 py-1.5 text-xs text-white hover:bg-amber-700"
          onClick={() => { void takeover(); }}
        >
          在此继续
        </button>
      </div>
    </div>
  );
}
