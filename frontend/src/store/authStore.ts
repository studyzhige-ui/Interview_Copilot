import { cancelNativeAuthFlow } from '@/lib/desktopAuth';
import { invalidateAuthAttempts } from '@/lib/supabaseAuth';
import { queryClient } from '@/lib/queryClient';
import { create } from 'zustand';
import { tokenStore, decodeJwtPayload } from '@/lib/token';
import { getMe, logout as apiLogout, type MeResponse } from '@/api/auth';

interface AuthState {
  subjectId: string | null;
  isAuthed: boolean;
  me: MeResponse | null;
  loadingMe: boolean;
  setSession: (access: string, refresh: string) => void;
  /** Server-side revoke + local clear. Always resolves. */
  logout: () => Promise<void>;
  clearSession: () => void;
  fetchMe: (force?: boolean) => Promise<MeResponse | null>;
  setMe: (m: MeResponse) => void;
}

function readSubjectFromToken(): string | null {
  const t = tokenStore.getAccess();
  if (!t) return null;
  const p = decodeJwtPayload<{ sub?: string }>(t);
  return p?.sub ?? null;
}

let epoch = 0;

export const useAuthStore = create<AuthState>((set, get) => ({
  subjectId: readSubjectFromToken(),
  isAuthed: !!tokenStore.getAccess(),
  me: null,
  loadingMe: false,
  setSession: (access, refresh) => {
    const previous = get().subjectId;
    const p = decodeJwtPayload<{ sub?: string }>(access);
    if (previous !== p?.sub) {
      epoch += 1;
      void queryClient.cancelQueries();
      queryClient.clear();
    }
    tokenStore.set(access, refresh);
    set({ subjectId: p?.sub ?? null, isAuthed: true, me: previous === p?.sub ? get().me : null, loadingMe: false });
  },
  clearSession: () => {
    invalidateAuthAttempts();
    epoch += 1;
    tokenStore.clear();
    void queryClient.cancelQueries();
    queryClient.clear();
    set({ subjectId: null, isAuthed: false, me: null, loadingMe: false });
  },
  logout: async () => {
    // Capture/revoke the old credentials in apiLogout before clearing. Local
    // privacy is immediate even if cloud Auth or the local API is unreachable.
    void cancelNativeAuthFlow().catch(() => undefined);
    const revocation = apiLogout();
    get().clearSession();
    void revocation.catch(() => undefined);
  },
  fetchMe: async (force = false) => {
    if (!get().isAuthed) return null;
    if (!force && get().me) return get().me;
    if (get().loadingMe) return get().me;
    const version = epoch;
    set({ loadingMe: true });
    try {
      const m = await getMe();
      if (epoch !== version) return null;
      set({ me: m, loadingMe: false });
      return m;
    } catch {
      if (epoch === version) set({ loadingMe: false });
      return null;
    }
  },
  setMe: (m) => set({ me: m }),
}));
