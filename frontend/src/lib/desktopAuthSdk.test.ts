/** Real pinned SDK. All fetch responses and credentials are synthetic. */
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
const code = 'synthetic-native-code-not-a-real-authentication-secret';
let cleanup: (() => void) | undefined;
beforeEach(() => { vi.resetModules(); localStorage.clear(); window.history.replaceState(null, '', '/auth'); });
afterEach(() => { cleanup?.(); cleanup = undefined; vi.unstubAllGlobals(); });
function session() {
  const id = '00000000-0000-4000-8000-000000000002', exp = Math.floor(Date.now() / 1000) + 3600;
  const encode = (value: object) => btoa(JSON.stringify(value)).replace(/=/g, '').replace(/\+/g, '-').replace(/\//g, '_');
  return { access_token: `${encode({ alg: 'HS256', typ: 'JWT' })}.${encode({ iss: 'https://fixture.supabase.co/auth/v1', sub: id, session_id: 'native-recovery-B', aud: 'authenticated', exp, iat: exp - 3600 })}.ZmFrZQ`, refresh_token: 'synthetic-native-refresh', expires_at: exp, expires_in: 3600, token_type: 'bearer', user: { id, aud: 'authenticated', email: 'B@example.test', email_confirmed_at: '2026-01-01T00:00:00Z', created_at: '', app_metadata: {}, user_metadata: {} } };
}
async function setup(verifier: 'recovery' | 'signup' | null, purpose: 'recovery' | 'signup', expired = false) {
  if (verifier) localStorage.setItem('sb-fixture-auth-token-code-verifier', JSON.stringify(`original-native-verifier${verifier === 'recovery' ? '/recovery' : ''}`));
  const b = session(), calls: Array<{ url: string; init?: RequestInit }> = [];
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input); calls.push({ url, init });
    const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
    if (url.includes('/auth/config')) return json({ provider: 'supabase', supabase_url: 'https://fixture.supabase.co', publishable_key: 'sb_publishable_fixture' });
    if (url.includes('grant_type=pkce')) return expired ? json({ code: 'otp_expired', msg: 'synthetic expired code' }, 400) : json(b);
    if (url.includes('/auth/v1/user')) return json(b.user);
    if (url.includes('/auth/v1/logout')) return new Response(null, { status: 204 });
    throw new Error('Unexpected external request');
  }));
  const auth = await import('./supabaseAuth'); const { tokenStore } = await import('./token');
  tokenStore.clear(); // A prior explicit logout must not erase the pending PKCE verifier on restart.
  const sink = vi.fn();
  await auth.initializeAuth(value => { sink(value); if (value) tokenStore.set(value.access_token, value.refresh_token); else tokenStore.clear(); }, { id: 'native-intent', purpose, code });
  cleanup = () => { void auth.cloudAuth().auth.stopAutoRefresh(); };
  return { auth, calls, b, sink, tokenStore };
}
it('cold native recovery exchanges the original verifier and proves B before updating B', async () => {
  const { auth, calls, b, tokenStore } = await setup('recovery', 'recovery');
  expect(auth.getRecoveryState()).toMatchObject({ status: 'ready', email: 'B@example.test' });
  expect(tokenStore.getAccess()).toBeNull();
  const exchange = calls.find(item => item.url.includes('grant_type=pkce'))!;
  expect(JSON.parse(String(exchange.init?.body))).toEqual({ auth_code: code, code_verifier: 'original-native-verifier' });
  expect(calls.some(item => item.url.includes('/logout'))).toBe(false);
  expect(await auth.completePasswordRecovery('synthetic-new-password-for-B')).toBe(true);
  const update = calls.find(item => item.init?.method === 'PUT')!;
  expect(new Headers(update.init?.headers).get('Authorization')).toBe(`Bearer ${b.access_token}`);
});
it.each([['signup', false], [null, false], ['recovery', true]] as const)('native recovery rejects verifier=%s expired=%s without password mutation', async (verifier, expired) => {
  const { auth, calls, tokenStore } = await setup(verifier, 'recovery', expired);
  expect(auth.getRecoveryState().status).toBe('failed'); expect(tokenStore.getAccess()).toBeNull();
  await expect(auth.completePasswordRecovery('must-not-be-sent')).rejects.toThrow('有效的重置会话');
  expect(calls.some(item => item.init?.method === 'PUT')).toBe(false);
});
it('native email confirmation returns to explicit login without silently binding a local owner', async () => {
  const { auth, tokenStore, sink } = await setup('signup', 'signup');
  expect(auth.getAuthCallbackNotice()).toContain('邮箱验证已完成');
  expect(tokenStore.getAccess()).toBeNull(); expect(sink.mock.calls.every(([value]) => value === null)).toBe(true);
  expect(auth.getRecoveryState().status).toBe('none');
});
