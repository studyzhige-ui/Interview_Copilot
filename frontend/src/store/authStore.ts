import { create } from 'zustand';
import { tokenStore, decodeJwtPayload } from '@/lib/token';
import { getMe, type MeResponse } from '@/api/auth';

interface AuthState {
  username: string | null;
  isAuthed: boolean;
  me: MeResponse | null;
  loadingMe: boolean;
  hydrate: () => void;
  setSession: (access: string, refresh: string) => void;
  logout: () => void;
  fetchMe: (force?: boolean) => Promise<MeResponse | null>;
  setMe: (m: MeResponse) => void;
}

function readUsernameFromToken(): string | null {
  const t = tokenStore.getAccess();
  if (!t) return null;
  const p = decodeJwtPayload<{ sub?: string }>(t);
  return p?.sub ?? null;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  username: readUsernameFromToken(),
  isAuthed: !!tokenStore.getAccess(),
  me: null,
  loadingMe: false,
  hydrate: () => {
    set({
      username: readUsernameFromToken(),
      isAuthed: !!tokenStore.getAccess(),
    });
  },
  setSession: (access, refresh) => {
    tokenStore.set(access, refresh);
    const p = decodeJwtPayload<{ sub?: string }>(access);
    set({ username: p?.sub ?? null, isAuthed: true, me: null });
  },
  logout: () => {
    tokenStore.clear();
    set({ username: null, isAuthed: false, me: null });
  },
  fetchMe: async (force = false) => {
    if (!get().isAuthed) return null;
    if (!force && get().me) return get().me;
    if (get().loadingMe) return get().me;
    set({ loadingMe: true });
    try {
      const m = await getMe();
      set({ me: m, loadingMe: false });
      return m;
    } catch {
      set({ loadingMe: false });
      return null;
    }
  },
  setMe: (m) => set({ me: m }),
}));
