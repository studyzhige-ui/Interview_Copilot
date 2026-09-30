import { beforeEach, expect, it, vi } from 'vitest';
const api = vi.hoisted(() => ({ getMe: vi.fn(), logout: vi.fn() }));
vi.mock('@/api/auth', () => api);
import { useAuthStore } from './authStore';
import { queryClient } from '@/lib/queryClient';

function token(sub: string) { return `test.${btoa(JSON.stringify({ sub }))}.signature`; }
beforeEach(() => { useAuthStore.getState().clearSession(); vi.clearAllMocks(); });

it('clears cached business data when the authenticated owner changes', () => {
  useAuthStore.getState().setSession(token('alice'), 'a'); queryClient.setQueryData(['records'], ['private-alice']);
  useAuthStore.getState().setSession(token('bob'), 'b');
  expect(queryClient.getQueryData(['records'])).toBeUndefined(); expect(useAuthStore.getState().me).toBeNull();
});

it('ignores a prior owner profile that arrives after switching accounts', async () => {
  let resolve!: (v: unknown) => void;
  api.getMe.mockReturnValue(new Promise(r => { resolve = r; }));
  useAuthStore.getState().setSession(token('alice'), 'a'); const pending = useAuthStore.getState().fetchMe();
  useAuthStore.getState().setSession(token('bob'), 'b'); resolve({ username: 'alice' }); await pending;
  expect(useAuthStore.getState().subjectId).toBe('bob'); expect(useAuthStore.getState().me).toBeNull();
});
