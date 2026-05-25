import { create } from 'zustand';

export type ToastKind = 'success' | 'info' | 'warning' | 'danger';
export interface ToastItem {
  id: number;
  kind: ToastKind;
  message: string;
}

interface UIState {
  toasts: ToastItem[];
  pushToast: (kind: ToastKind, message: string, ttl?: number) => void;
  dismissToast: (id: number) => void;
}

let _id = 0;

// Track outstanding TTL timers so ``dismissToast`` (or a fast manual
// dismiss) can cancel them. Without this, a user clicking dismiss
// followed by the timer firing later would call ``dismissToast(id)``
// against an already-removed item — harmless (the filter just no-ops)
// but wasteful, and it prevents the timer from getting garbage-
// collected promptly. Storing handles also lets us clean them up on
// HMR teardown so a dev refresh doesn't leak.
const _pendingTimers = new Map<number, ReturnType<typeof setTimeout>>();

export const useUIStore = create<UIState>((set, get) => ({
  toasts: [],
  pushToast: (kind, message, ttl = 3000) => {
    const id = ++_id;
    set({ toasts: [...get().toasts, { id, kind, message }] });
    if (ttl > 0) {
      const handle = setTimeout(() => {
        _pendingTimers.delete(id);
        get().dismissToast(id);
      }, ttl);
      _pendingTimers.set(id, handle);
    }
  },
  dismissToast: (id) => {
    const handle = _pendingTimers.get(id);
    if (handle !== undefined) {
      clearTimeout(handle);
      _pendingTimers.delete(id);
    }
    set({ toasts: get().toasts.filter((t) => t.id !== id) });
  },
}));

export const toast = {
  success: (m: string) => useUIStore.getState().pushToast('success', m),
  info:    (m: string) => useUIStore.getState().pushToast('info', m),
  warn:    (m: string) => useUIStore.getState().pushToast('warning', m),
  error:   (m: string) => useUIStore.getState().pushToast('danger', m, 5000),
};
