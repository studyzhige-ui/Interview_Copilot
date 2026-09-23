import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import axios from 'axios';
import { authedFetch } from './client';
import { tokenStore } from '@/lib/token';

describe('refresh recovery', () => {
  beforeEach(() => {
    tokenStore.set('old-access', 'old-refresh');
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
      data: { access_token: 'new-access', refresh_token: 'new-refresh' },
    });
    const responses = await Promise.all([authedFetch('/a'), authedFetch('/b')]);
    expect(responses.every((response) => response.ok)).toBe(true);
    expect(post).toHaveBeenCalledTimes(1);
    expect(new Headers(vi.mocked(fetch).mock.calls[3][1]?.headers).get('Authorization')).toBe('Bearer new-access');
  });

  it('reuses another tab rotation that completed while this request was in flight', async () => {
    vi.mocked(fetch).mockImplementationOnce(async () => {
      tokenStore.set('other-tab-access', 'other-tab-refresh');
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
      tokenStore.set('other-account-access', 'other-account-refresh');
      return { data: { access_token: 'late-access', refresh_token: 'late-refresh' } };
    });
    await authedFetch('/test');
    expect(tokenStore.getAccess()).toBe('other-account-access');
  });
});
