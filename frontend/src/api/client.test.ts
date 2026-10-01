import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import axios, { AxiosError } from 'axios';
const cloud = vi.hoisted(() => ({ enabled: false, refresh: vi.fn() }));
vi.mock('@/lib/supabaseAuth', () => ({ isSupabaseAuth: () => cloud.enabled, refreshCloudAccess: cloud.refresh, invalidateAuthAttempts: vi.fn() }));
import { apiClient, authedFetch } from './client';
import { tokenStore } from '@/lib/token';

const token = (subject = 'A', rotation = 'old', session = 'session-A') => `e30.${btoa(JSON.stringify({ iss: 'fixture', sub: subject, session_id: session, jti: rotation }))}.signature`;
const oldAccess = token();
const newAccess = token('A', 'new');
const otherAccess = token('B', 'old', 'session-B');
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(r => { resolve = r; }); return { promise, resolve }; }

describe('refresh recovery', () => {
  beforeEach(() => {
    cloud.enabled = false; cloud.refresh.mockReset();
    tokenStore.set(oldAccess, 'old-refresh');
    vi.stubGlobal('fetch', vi.fn());
  });
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    tokenStore.clear();
  });

  it('keeps credentials when the refresh service is temporarily unavailable', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(null, { status: 401 }));
    vi.spyOn(axios, 'post').mockRejectedValue(new Error('offline'));
    await expect(authedFetch('/test')).rejects.toThrow('offline');
    expect(tokenStore.getRefresh()).toBe('old-refresh');
  });

  it('coalesces simultaneous failures and retries with the rotated access token', async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(new Response(null, { status: 401 }))
      .mockResolvedValueOnce(new Response(null, { status: 401 }))
      .mockResolvedValue(new Response(null, { status: 200 }));
    const post = vi.spyOn(axios, 'post').mockResolvedValue({
      data: { access_token: newAccess, refresh_token: 'new-refresh' },
    });
    const responses = await Promise.all([authedFetch('/a'), authedFetch('/b')]);
    expect(responses.every((response) => response.ok)).toBe(true);
    expect(post).toHaveBeenCalledTimes(1);
    expect(new Headers(vi.mocked(fetch).mock.calls[3][1]?.headers).get('Authorization')).toBe(`Bearer ${newAccess}`);
  });

  it('reuses another tab rotation that completed while this request was in flight', async () => {
    vi.mocked(fetch).mockImplementationOnce(async () => {
      tokenStore.set(newAccess, 'other-tab-refresh');
      return new Response(null, { status: 401 });
    }).mockResolvedValue(new Response(null, { status: 200 }));
    const post = vi.spyOn(axios, 'post');
    expect((await authedFetch('/test')).ok).toBe(true);
    expect(post).not.toHaveBeenCalled();
    expect(tokenStore.getRefresh()).toBe('other-tab-refresh');
  });

  it('does not overwrite a new account with a late refresh response', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response(null, { status: 401 }))
      .mockResolvedValue(new Response(null, { status: 200 }));
    vi.spyOn(axios, 'post').mockImplementationOnce(async () => {
      tokenStore.set(otherAccess, 'other-account-refresh');
      return { data: { access_token: newAccess, refresh_token: 'late-refresh' } };
    });
    await expect(authedFetch('/test')).rejects.toThrow('账号会话已变化');
    expect(tokenStore.getAccess()).toBe(otherAccess);
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});


describe('request authority isolation', () => {
  beforeEach(() => { cloud.enabled = true; cloud.refresh.mockReset(); tokenStore.clear(); });
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); tokenStore.clear(); cloud.enabled = false; });

  for (const transport of ['fetch', 'axios'] as const) {
    it(`${transport}: refuses A mutation joining B's refresh; B still rotates normally`, async () => {
      const failA = deferred<void>();
      const finishB = deferred<string>();
      const calls: Array<{ url: string; auth: string | null; body: unknown }> = [];
      const freshB = token('B', 'new', 'session-B');
      cloud.refresh.mockImplementation(async () => { const value = await finishB.promise; tokenStore.set(value, 'B-new-refresh'); return value; });
      const respond = async (url: string, auth: string | null, body: unknown) => {
        calls.push({ url, auth, body });
        if (url === '/mutate-A' && auth === `Bearer ${oldAccess}`) { await failA.promise; return 401; }
        return auth === `Bearer ${freshB}` ? 200 : 401;
      };
      vi.stubGlobal('fetch', vi.fn(async (url, init) => new Response(null, { status: await respond(String(url), new Headers(init?.headers).get('Authorization'), init?.body) })));
      const adapter = vi.fn(async config => {
        const status = await respond(config.url, config.headers.get('Authorization'), config.data);
        const response = { status, data: {}, statusText: '', headers: {}, config };
        if (status === 401) throw new AxiosError('unauthorized', 'ERR_BAD_REQUEST', config, undefined, response);
        return response;
      });
      const send = (owner: string) => transport === 'fetch'
        ? authedFetch(`/mutate-${owner}`, { method: 'POST', body: `${owner}-intended-edit` })
        : apiClient.post(`/mutate-${owner}`, `${owner}-intended-edit`, { adapter });
      tokenStore.set(oldAccess, 'refresh-A');
      const requestA = send('A');
      const rejectedA = expect(requestA).rejects.toThrow('账号会话已变化');
      tokenStore.set(otherAccess, 'refresh-B');
      const requestB = send('B');
      await vi.waitFor(() => expect(cloud.refresh).toHaveBeenCalledWith(otherAccess));
      failA.resolve();
      await rejectedA;
      finishB.resolve(freshB);
      await requestB;
      expect(cloud.refresh).toHaveBeenCalledTimes(1);
      expect(calls.filter(call => call.url === '/mutate-A')).toEqual([{ url: '/mutate-A', auth: `Bearer ${oldAccess}`, body: 'A-intended-edit' }]);
      expect(calls.filter(call => call.url === '/mutate-B').map(call => call.auth)).toEqual([`Bearer ${otherAccess}`, `Bearer ${freshB}`]);
    });

    it(`${transport}: rejects logout/relogin even into the same subject/session`, async () => {
      const failure = deferred<void>();
      vi.stubGlobal('fetch', vi.fn(async () => { await failure.promise; return new Response(null, { status: 401 }); }));
      const adapter = vi.fn(async config => { await failure.promise; throw new AxiosError('unauthorized', 'ERR_BAD_REQUEST', config, undefined, { status: 401, data: {}, statusText: '', headers: {}, config }); });
      tokenStore.set(oldAccess, 'refresh-A');
      const request = transport === 'fetch' ? authedFetch('/mutation', { method: 'POST' }) : apiClient.post('/mutation', {}, { adapter });
      const rejected = expect(request).rejects.toThrow('账号会话已变化');
      tokenStore.clear(); tokenStore.set(oldAccess, 'refresh-A');
      failure.resolve(); await rejected;
      expect(cloud.refresh).not.toHaveBeenCalled();
      expect(transport === 'fetch' ? fetch : adapter).toHaveBeenCalledTimes(1);
      expect(tokenStore.getAccess()).toBe(oldAccess);
    });
  }

  it('shares a same-authority flight across fetch and Axios and pins both retries', async () => {
    const rotation = deferred<string>();
    const sent: string[] = [];
    tokenStore.set(oldAccess, 'refresh-A');
    cloud.refresh.mockImplementation(async () => {
      const fresh = await rotation.promise;
      tokenStore.set(fresh, 'refresh-A-new');
      return fresh;
    });
    vi.stubGlobal('fetch', vi.fn(async (_url, init) => {
      const auth = new Headers(init?.headers).get('Authorization')!; sent.push(auth);
      return new Response(null, { status: auth === `Bearer ${newAccess}` ? 200 : 401 });
    }));
    const adapter = vi.fn(async config => {
      const auth = config.headers.get('Authorization'); sent.push(auth);
      const response = { status: auth === `Bearer ${newAccess}` ? 200 : 401, data: {}, statusText: '', headers: {}, config };
      if (response.status === 401) throw new AxiosError('unauthorized', 'ERR_BAD_REQUEST', config, undefined, response);
      return response;
    });
    const requests = Promise.all([authedFetch('/fetch', { method: 'POST' }), apiClient.post('/axios', {}, { adapter })]);
    await vi.waitFor(() => expect(cloud.refresh).toHaveBeenCalledTimes(1));
    rotation.resolve(newAccess); await requests;
    expect(cloud.refresh).toHaveBeenCalledTimes(1);
    expect(sent).toEqual([`Bearer ${oldAccess}`, `Bearer ${oldAccess}`, `Bearer ${newAccess}`, `Bearer ${newAccess}`]);
  });

  it('does not reuse a different cloud session of the same subject', async () => {
    tokenStore.set(oldAccess, 'old-refresh');
    vi.stubGlobal('fetch', vi.fn(async () => {
      tokenStore.set(token('A', 'new-login', 'session-new'), 'different-session-refresh');
      return new Response(null, { status: 401 });
    }));
    await expect(authedFetch('/mutation', { method: 'POST' })).rejects.toThrow('账号会话已变化');
    expect(cloud.refresh).not.toHaveBeenCalled(); expect(fetch).toHaveBeenCalledTimes(1);
  });
});
