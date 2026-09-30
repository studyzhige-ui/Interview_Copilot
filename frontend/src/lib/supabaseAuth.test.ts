import { beforeEach, expect, it, vi } from 'vitest';
const sdk = vi.hoisted(() => ({ createClient: vi.fn(), getSession: vi.fn(), refreshSession: vi.fn(), onAuthStateChange: vi.fn() }));
vi.mock('@supabase/supabase-js', () => ({ createClient: sdk.createClient }));
import { tokenStore } from './token';
function jwt(payload: object) { return `head.${btoa(JSON.stringify(payload))}.signature`; }

beforeEach(() => {
  vi.resetModules(); vi.clearAllMocks(); localStorage.clear();
  sdk.getSession.mockResolvedValue({ data: { session: null } });
  sdk.onAuthStateChange.mockReturnValue({ data: { subscription: { unsubscribe: vi.fn() } } });
  sdk.createClient.mockReturnValue({ auth: sdk });
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ provider: 'supabase', supabase_url: 'https://fixture.supabase.co', publishable_key: 'sb_publishable_fixture' }) }));
});

it('uses PKCE and a publishable key from the local API without embedding a secret', async () => {
  const auth = await import('./supabaseAuth'); await auth.initializeAuth(vi.fn());
  expect(sdk.createClient).toHaveBeenCalledWith('https://fixture.supabase.co', 'sb_publishable_fixture', expect.objectContaining({ auth: expect.objectContaining({ flowType: 'pkce', detectSessionInUrl: true }) }));
});

it('never falls back to local registration for an invalid cloud configuration', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ provider: 'supabase', supabase_url: 'https://fixture.supabase.co', publishable_key: 'sb_secret_forbidden' }) }));
  const auth = await import('./supabaseAuth'); await expect(auth.initializeAuth(vi.fn())).rejects.toThrow('配置不完整');
  expect(sdk.createClient).not.toHaveBeenCalled();
});

it('a background cloud event cannot replace an explicitly unlocked local session', async () => {
  tokenStore.set(jwt({ sub: '7', type: 'local_unlock' }), '');
  const callback = vi.fn(); const auth = await import('./supabaseAuth'); await auth.initializeAuth(callback);
  const notify = sdk.onAuthStateChange.mock.calls[0][0];
  notify('TOKEN_REFRESHED', { access_token: 'cloud-token', refresh_token: 'cloud-refresh' });
  expect(callback).not.toHaveBeenCalled();
  expect(await auth.refreshCloudAccess(tokenStore.getAccess())).toBeNull(); expect(sdk.refreshSession).not.toHaveBeenCalled();
});

it('ignores cloud refresh completion after local logout', async () => {
  const auth = await import('./supabaseAuth'); await auth.initializeAuth(vi.fn());
  tokenStore.set(jwt({ iss: 'https://fixture.supabase.co/auth/v1', sub: 'cloud-user' }), 'old-refresh');
  let resolve!: (value: unknown) => void;
  sdk.refreshSession.mockReturnValue(new Promise(r => { resolve = r; }));
  const pending = auth.refreshCloudAccess(tokenStore.getAccess()); tokenStore.clear();
  resolve({ data: { session: { access_token: 'late', refresh_token: 'late' } }, error: null });
  expect(await pending).toBeNull(); expect(tokenStore.getAccess()).toBeNull();
});

it('serializes sign-out before a later new sign-in', async () => {
  const auth = await import('./supabaseAuth'); const order: string[] = [];
  let finish!: () => void;
  const first = auth.runCloudAuthOperation(() => new Promise<void>(resolve => { order.push('logout'); finish = resolve; }));
  const second = auth.runCloudAuthOperation(async () => { order.push('login'); });
  await Promise.resolve(); expect(order).toEqual(['logout']); finish(); await first; await second;
  expect(order).toEqual(['logout', 'login']);
});
