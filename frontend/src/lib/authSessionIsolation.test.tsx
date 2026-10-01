import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { AuthChangeEvent, Session } from '@supabase/supabase-js';
import { beforeEach, expect, it, vi } from 'vitest';
const f = vi.hoisted(() => ({
  notify: null as ((event: AuthChangeEvent, session: Session | null) => void) | null,
  current: null as Session | null,
  post: vi.fn(),
  auth: { onAuthStateChange: vi.fn(), getSession: vi.fn(), signInWithPassword: vi.fn(), refreshSession: vi.fn(), signOut: vi.fn() },
}));
vi.mock('@supabase/supabase-js', () => ({ createClient: () => ({ auth: f.auth }) }));
vi.mock('@/api/client', () => ({ apiClient: { post: f.post }, extractErr: (error: Error) => error.message }));
function session(sub: string, suffix = ''): Session {
  const access = `head.${btoa(JSON.stringify({ iss: 'https://fixture.supabase.co/auth/v1', sub, session_id: `session-${sub}`, nonce: suffix }))}.fake`;
  return { access_token: access, refresh_token: `refresh-${sub}${suffix}`, token_type: 'bearer', expires_in: 3600, user: { id: sub, aud: 'authenticated', email: `${sub}@example.test`, created_at: '', app_metadata: {}, user_metadata: {} } };
}
beforeEach(() => {
  vi.resetModules(); vi.clearAllMocks(); localStorage.clear(); window.history.replaceState(null, '', '/auth'); f.current = null;
  f.auth.onAuthStateChange.mockImplementation(listener => { f.notify = listener; return { data: { subscription: { unsubscribe: vi.fn() } } }; });
  f.auth.getSession.mockImplementation(async () => ({ data: { session: f.current }, error: null }));
  f.auth.signOut.mockImplementation(async () => { f.current = null; f.notify?.('SIGNED_OUT', null); return { error: null }; });
  f.post.mockResolvedValue({ data: { status: 'ok' } });
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ provider: 'supabase', supabase_url: 'https://fixture.supabase.co', publishable_key: 'sb_publishable_fixture' }) }));
});
async function setup() {
  const auth = await import('./supabaseAuth'); const { useAuthStore } = await import('@/store/authStore'); const { tokenStore } = await import('./token'); const { queryClient } = await import('./queryClient');
  await auth.initializeAuth(value => value ? useAuthStore.getState().setSession(value.access_token, value.refresh_token) : useAuthStore.getState().clearSession());
  const a = session('A'); f.current = a; auth.acceptCloudSession(a, auth.beginAuthAttempt());
  useAuthStore.getState().setMe({ username: 'local-owner-A', email: null, nickname: null, avatar_url: null, bio: null, email_verified: true, created_at: '', updated_at: '', default_execution_mode: 'standard' });
  queryClient.setQueryData(['private-local-items'], ['A-private-content']);
  return { auth, a, useAuthStore, tokenStore, queryClient };
}

it('a failed B binding clears A data and discards B rather than creating a mixed account', async () => {
  const { auth, a, useAuthStore, tokenStore, queryClient } = await setup(); const b = session('B');
  f.auth.signInWithPassword.mockImplementation(async () => { f.current = b; f.notify?.('SIGNED_IN', b); return { data: { session: b }, error: null }; });
  f.post.mockRejectedValue(new Error('Local binding requires proof'));
  const { SupabaseAuthPanel } = await import('@/pages/auth/SupabaseAuthPanel');
  render(<MemoryRouter><SupabaseAuthPanel /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText('邮箱'), { target: { value: 'B@example.test' } });
  fireEvent.change(screen.getByLabelText('账号密码'), { target: { value: 'password-B' } });
  fireEvent.click(screen.getByRole('button', { name: '统一账号登录' }));
  await screen.findByRole('alert'); await waitFor(() => expect(f.current).toBeNull());
  expect(tokenStore.getAccess()).toBeNull(); expect(useAuthStore.getState().subjectId).toBeNull();
  expect(useAuthStore.getState().me).toBeNull(); expect(queryClient.getQueryData(['private-local-items'])).toBeUndefined();
  expect(await auth.refreshCloudAccess(a.access_token)).toBeNull(); expect(f.auth.refreshSession).not.toHaveBeenCalled();
});

it('refresh cannot return B to replay a request originally authorized as A', async () => {
  const { auth, a, useAuthStore, tokenStore } = await setup(); const b = session('B');
  f.auth.refreshSession.mockImplementation(async () => { f.current = b; f.notify?.('TOKEN_REFRESHED', b); return { data: { session: b }, error: null }; });
  expect(await auth.refreshCloudAccess(a.access_token)).toBeNull();
  expect(tokenStore.getAccess()).toBe(a.access_token); expect(useAuthStore.getState().subjectId).toBe('A');
});

it('a late A refresh neither overwrites B nor returns B as an A retry token', async () => {
  const { auth, a, useAuthStore, tokenStore, queryClient } = await setup();
  let resolve!: (value: unknown) => void; f.auth.refreshSession.mockReturnValue(new Promise(r => { resolve = r; }));
  const pending = auth.refreshCloudAccess(a.access_token); const b = session('B');
  auth.acceptCloudSession(b, auth.beginAuthAttempt());
  resolve({ data: { session: session('A', 'late') }, error: null });
  expect(await pending).toBeNull(); expect(tokenStore.getAccess()).toBe(b.access_token);
  expect(useAuthStore.getState().subjectId).toBe('B'); expect(queryClient.getQueryData(['private-local-items'])).toBeUndefined();
});

it('same-account refresh updates transport and UI through the same synchronous sink', async () => {
  const { auth, a, useAuthStore, tokenStore } = await setup(); const fresh = session('A', 'fresh');
  f.auth.refreshSession.mockResolvedValue({ data: { session: fresh }, error: null });
  expect(await auth.refreshCloudAccess(a.access_token)).toBe(fresh.access_token);
  expect(tokenStore.getAccess()).toBe(fresh.access_token); expect(useAuthStore.getState().subjectId).toBe('A');
});

it('logout clears local access/cache before a stalled cloud sign-out and stays locked on reload', async () => {
  const { auth, a, useAuthStore, tokenStore, queryClient } = await setup();
  let finish!: () => void; const stalled = new Promise<{ error: null }>(r => { finish = () => r({ error: null }); });
  f.auth.signOut.mockReturnValue(stalled);
  await act(async () => { await useAuthStore.getState().logout(); });
  expect(tokenStore.getAccess()).toBeNull(); expect(tokenStore.isLocked()).toBe(true);
  expect(useAuthStore.getState().isAuthed).toBe(false); expect(queryClient.getQueryData(['private-local-items'])).toBeUndefined();
  f.current = a;
  await auth.initializeAuth(value => value ? useAuthStore.getState().setSession(value.access_token, value.refresh_token) : useAuthStore.getState().clearSession());
  await Promise.resolve(); expect(useAuthStore.getState().isAuthed).toBe(false);
  finish(); await Promise.resolve();
});
