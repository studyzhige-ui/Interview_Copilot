import { useCallback, useEffect, useState } from 'react';
import { toast } from '@/store/uiStore';
import { extractErr } from '@/api/client';
import { getSessionGlobalMemory, setSessionGlobalMemory } from '@/api/chat';

/**
 * Global-memory toggle (per-session resolved value).
 *
 * The button reflects the effective per-session value (the
 * global_memory_enabled column override → user-level default → False).
 * Toggling writes the override into that column so this session diverges
 * from the user-level default for subsequent turns.
 */
export function useGlobalMemoryToggle(activeSessionId: string | null) {
  const [memoryState, setMemoryState] = useState({ sessionId: activeSessionId, enabled: false });
  const [togglingMemory, setTogglingMemory] = useState(false);
  const globalMemoryOn = memoryState.sessionId === activeSessionId
    ? memoryState.enabled
    : false;

  useEffect(() => {
    if (!activeSessionId) return;
    // Same race shape as the transcript-load effect — abort on
    // session switch so a stale response from session A can't
    // overwrite session B's toggle state, and the backend doesn't
    // keep materialising the abandoned response.
    const controller = new AbortController();
    let alive = true;
    getSessionGlobalMemory(activeSessionId, { signal: controller.signal })
      .then((enabled) => {
        if (alive) setMemoryState({ sessionId: activeSessionId, enabled });
      })
      .catch(() => { /* empty / aborted on switch — both fine */ });
    return () => {
      alive = false;
      controller.abort();
    };
  }, [activeSessionId]);

  const toggleGlobalMemory = useCallback(async () => {
    if (!activeSessionId || togglingMemory) return;
    const next = !globalMemoryOn;
    setMemoryState({ sessionId: activeSessionId, enabled: next });
    setTogglingMemory(true);
    try { await setSessionGlobalMemory(activeSessionId, next); }
    catch (e) {
      setMemoryState({ sessionId: activeSessionId, enabled: !next });
      toast.error(extractErr(e, '切换全局记忆失败'));
    } finally { setTogglingMemory(false); }
  }, [activeSessionId, globalMemoryOn, togglingMemory]);

  return { globalMemoryOn, togglingMemory, toggleGlobalMemory };
}
