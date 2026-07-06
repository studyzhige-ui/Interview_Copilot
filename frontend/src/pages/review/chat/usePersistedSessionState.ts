import { useCallback, useEffect, useState } from 'react';
import type { Mode } from './types';

/**
 * Draft persists per-session in localStorage so navigating away
 * (sidebar / different page) and back doesn't lose what the user
 * was typing. Same pattern as ``useSessionMode`` below — pure-React
 * state alone gets wiped on every ChatPanel unmount.
 *
 * We intentionally do NOT wire a ``storage`` event listener: if the
 * user has the same session open in two tabs, typing in tab A won't
 * live-update tab B's input. That's an acceptable edge case (dual-
 * tabbing the same session is rare) and avoids cursor-position
 * weirdness across tabs.
 */
export function useSessionDraft(activeSessionId: string | null) {
  const draftStorageKey = activeSessionId ? `chat-draft:${activeSessionId}` : null;
  const [input, setInputState] = useState<string>(() => {
    if (!draftStorageKey) return '';
    try { return localStorage.getItem(draftStorageKey) ?? ''; }
    catch { return ''; }
  });
  const setInput = useCallback((next: string) => {
    setInputState(next);
    if (draftStorageKey) {
      try {
        if (next) localStorage.setItem(draftStorageKey, next);
        else localStorage.removeItem(draftStorageKey);
      } catch { /* quota / privacy mode */ }
    }
  }, [draftStorageKey]);
  // Re-read draft when the active session changes (sidebar switch).
  useEffect(() => {
    if (!draftStorageKey) { setInputState(''); return; }
    try { setInputState(localStorage.getItem(draftStorageKey) ?? ''); }
    catch { /* ignore */ }
  }, [draftStorageKey]);
  return { input, setInput };
}

/**
 * Mode is persisted per-session in localStorage — without this the
 * user's AGENT pill resets to CHAT every time they refresh, and the
 * backend silently downgrades the strategy back to L1. We key by
 * session_id so a chat session and an agent session can co-exist.
 * The backend column (conversations.mode) is authoritative (AGT-4);
 * localStorage is just the zero-round-trip cache, seeded from the
 * server's session list on a fresh device.
 */
export function useSessionMode(activeSessionId: string | null, serverMode?: string) {
  const modeStorageKey = activeSessionId ? `chat-mode:${activeSessionId}` : null;
  const [mode, setModeState] = useState<Mode>(() => {
    if (!modeStorageKey) return 'CHAT';
    try {
      const v = localStorage.getItem(modeStorageKey);
      if (v === 'AGENT' || v === 'CHAT') return v;
    } catch { /* fall through */ }
    // AGT-4: no local entry (fresh device) — the server's persisted
    // conversations.mode is authoritative instead of silently CHAT.
    return serverMode === 'agent' ? 'AGENT' : 'CHAT';
  });
  const setMode = useCallback((next: Mode | ((prev: Mode) => Mode)) => {
    setModeState((prev) => {
      const resolved = typeof next === 'function' ? next(prev) : next;
      if (modeStorageKey) {
        try { localStorage.setItem(modeStorageKey, resolved); } catch { /* quota */ }
      }
      return resolved;
    });
  }, [modeStorageKey]);
  // When the active session changes (sidebar switch), re-read mode for
  // the newly-active session. Without this, switching from an AGENT
  // session back to a CHAT one would show the wrong pill.
  useEffect(() => {
    if (!modeStorageKey) return;
    try {
      const v = localStorage.getItem(modeStorageKey);
      setModeState(v === 'AGENT' ? 'AGENT' : 'CHAT');
    } catch { /* ignore */ }
  }, [modeStorageKey]);
  return { mode, setMode };
}

/** Remove the persisted draft + mode for a deleted session so
 *  localStorage doesn't accumulate orphaned keys. */
export function clearPersistedSessionState(sessionId: string) {
  try { localStorage.removeItem(`chat-draft:${sessionId}`); } catch { /* ignore */ }
  try { localStorage.removeItem(`chat-mode:${sessionId}`); } catch { /* ignore */ }
}
