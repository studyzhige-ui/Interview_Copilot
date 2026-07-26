import { useCallback, useState } from 'react';
import type { Mode } from './types';

function readDraft(key: string | null): string {
  if (!key) return '';
  try { return localStorage.getItem(key) ?? ''; }
  catch { return ''; }
}

function readMode(key: string | null, serverMode?: string): Mode {
  if (key) {
    try {
      const value = localStorage.getItem(key);
      if (value === 'AGENT' || value === 'CHAT') return value;
    } catch { /* use server value */ }
  }
  return serverMode === 'agent' ? 'AGENT' : 'CHAT';
}

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
  const [draft, setDraft] = useState(() => ({
    key: draftStorageKey,
    value: readDraft(draftStorageKey),
  }));
  const input = draft.key === draftStorageKey ? draft.value : readDraft(draftStorageKey);
  const setInput = useCallback((next: string) => {
    setDraft({ key: draftStorageKey, value: next });
    if (draftStorageKey) {
      try {
        if (next) localStorage.setItem(draftStorageKey, next);
        else localStorage.removeItem(draftStorageKey);
      } catch { /* quota / privacy mode */ }
    }
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
  const [modeState, setModeState] = useState(() => ({
    key: modeStorageKey,
    value: readMode(modeStorageKey, serverMode),
  }));
  const mode = modeState.key === modeStorageKey
    ? modeState.value
    : readMode(modeStorageKey, serverMode);
  const setMode = useCallback((next: Mode | ((prev: Mode) => Mode)) => {
    setModeState((prev) => {
      const current = prev.key === modeStorageKey
        ? prev.value
        : readMode(modeStorageKey, serverMode);
      const resolved = typeof next === 'function' ? next(current) : next;
      if (modeStorageKey) {
        try { localStorage.setItem(modeStorageKey, resolved); } catch { /* quota */ }
      }
      return { key: modeStorageKey, value: resolved };
    });
  }, [modeStorageKey, serverMode]);
  return { mode, setMode };
}

/** Remove the persisted draft + mode for a deleted session so
 *  localStorage doesn't accumulate orphaned keys. */
export function clearPersistedSessionState(sessionId: string) {
  try { localStorage.removeItem(`chat-draft:${sessionId}`); } catch { /* ignore */ }
  try { localStorage.removeItem(`chat-mode:${sessionId}`); } catch { /* ignore */ }
}
