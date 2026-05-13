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

export const useUIStore = create<UIState>((set, get) => ({
  toasts: [],
  pushToast: (kind, message, ttl = 3000) => {
    const id = ++_id;
    set({ toasts: [...get().toasts, { id, kind, message }] });
    if (ttl > 0) {
      setTimeout(() => get().dismissToast(id), ttl);
    }
  },
  dismissToast: (id) => set({ toasts: get().toasts.filter((t) => t.id !== id) }),
}));

export const toast = {
  success: (m: string) => useUIStore.getState().pushToast('success', m),
  info:    (m: string) => useUIStore.getState().pushToast('info', m),
  warn:    (m: string) => useUIStore.getState().pushToast('warning', m),
  error:   (m: string) => useUIStore.getState().pushToast('danger', m, 5000),
};
