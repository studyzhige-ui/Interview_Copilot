/** Actual pinned SDK + fake HTTP, never real users/passwords or network. */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

vi.mock('@/api/client', () => ({ apiClient: { post: vi.fn() }, extractErr: (error: Error) => error.message }));
const expiry = () => Math.floor(Date.now() / 1000) + 3600;
function session(letter: 'A' | 'B') {
  const id = letter === 'A' ? '00000000-0000-4000-8000-000000000001' : '00000000-0000-4000-8000-000000000002';
  const user = { id, aud: 'authenticated', email: `${letter}@example.test`, created_at: '2026-01-01T00:00:00Z', app_metadata: {}, user_metadata: {} };
  const enc = (value: object) => btoa(JSON.stringify(value));
  const access = `${enc({ alg: 'HS256', typ: 'JWT' })}.${enc({ iss: 'https://fixture.supabase.co/auth/v1', sub: id, session_id: `session-${letter}`, exp: expiry(), iat: expiry() - 3600, aud: 'authenticated' })}.ZmFrZQ`;
  return { access_token: access, refresh_token: `${letter}-refresh`, expires_at: expiry(), expires_in: 3600, token_type: 'bearer', user };
}
let stop: (() => void) | null = null;
beforeEach(() => { vi.resetModules(); localStorage.clear(); window.history.replaceState(null, '', '/auth?flow=recovery&code=recovery-B'); });
afterEach(() => { stop?.(); stop = null; vi.unstubAllGlobals(); });

async function setup(withVerifier: boolean, expired = false) {
  const a = session('A'); const b = session('B');
  localStorage.setItem('sb-fixture-auth-token', JSON.stringify(a));
  if (withVerifier) localStorage.setItem('sb-fixture-auth-token-code-verifier', JSON.stringify('fixture-verifier/recovery'));
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  vi.stubGlobal('fetch', vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const address = String(url); calls.push({ url: address, init });
    const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'content-type': 'application/json' } });
    if (address.includes('/auth/config')) return json({ provider: 'supabase', supabase_url: 'https://fixture.supabase.co', publishable_key: 'sb_publishable_fixture' });
    if (address.includes('grant_type=pkce')) return expired ? json({ code: 'otp_expired', msg: 'expired recovery code' }, 400) : json(b);
    if (address.includes('/auth/v1/user')) return json(new Headers(init?.headers).get('Authorization') === `Bearer ${b.access_token}` ? b.user : a.user);
    if (address.includes('/auth/v1/logout')) return new Response(null, { status: 204 });
    throw new Error(`Unexpected network: ${address}`);
  }));
  const auth = await import('./supabaseAuth');
  const { useAuthStore } = await import('@/store/authStore');
  const { queryClient } = await import('./queryClient');
  useAuthStore.getState().setSession(a.access_token, a.refresh_token);
  queryClient.setQueryData(['private-A'], ['private data']);
  await auth.initializeAuth(value => {
    if (value) useAuthStore.getState().setSession(value.access_token, value.refresh_token);
    else useAuthStore.getState().clearSession();
  });
  await auth.cloudAuth().auth.initialize();
  stop = () => { void auth.cloudAuth().auth.stopAutoRefresh(); };
  const { SupabaseAuthPanel } = await import('@/pages/auth/SupabaseAuthPanel');
  render(<MemoryRouter><SupabaseAuthPanel /></MemoryRouter>);
  return { auth, a, b, calls, useAuthStore, queryClient };
}

it.each([false, true])('never changes retained account A for a missing/expired B recovery proof (expired=%s)', async expired => {
  const { auth, calls, useAuthStore, queryClient } = await setup(expired, expired);
  await waitFor(() => expect(auth.getRecoveryState().status).toBe('failed'));
  expect(useAuthStore.getState().isAuthed).toBe(false);
  expect(queryClient.getQueryData(['private-A'])).toBeUndefined();
  const button = screen.getByRole('button', { name: '设置新账号密码' });
  expect(button).toBeDisabled();
  fireEvent.change(screen.getByLabelText('账号密码'), { target: { value: 'password-intended-for-B' } });
  fireEvent.change(screen.getByLabelText('再次输入密码'), { target: { value: 'password-intended-for-B' } });
  fireEvent.submit(button.closest('form')!); // Even bypassing the disabled button fails closed.
  await expect(auth.completePasswordRecovery('password-intended-for-B')).rejects.toThrow('有效的重置会话');
  expect(calls.some(call => call.url.includes('/auth/v1/user') && call.init?.method === 'PUT')).toBe(false);
});

it('binds a successful SDK recovery exchange to B even if the shared SDK storage changes to A', async () => {
  const { auth, a, b, calls } = await setup(true);
  await waitFor(() => expect(auth.getRecoveryState().status).toBe('ready'));
  expect(await screen.findByText('将重置 B@example.test 的账号密码')).toBeInTheDocument();
  // Simulate another tab changing shared storage before its event is delivered.
  localStorage.setItem('sb-fixture-auth-token', JSON.stringify(a));
  await act(async () => { expect(await auth.completePasswordRecovery('new-password-for-B')).toBe(true); });
  const updates = calls.filter(call => call.url.includes('/auth/v1/user') && call.init?.method === 'PUT');
  expect(updates).toHaveLength(1);
  expect(new Headers(updates[0].init?.headers).get('Authorization')).toBe(`Bearer ${b.access_token}`);
  expect(JSON.parse(String(updates[0].init?.body)).password).toBe('new-password-for-B');
  await expect(auth.completePasswordRecovery('second-reset')).rejects.toThrow('有效的重置会话');
});
